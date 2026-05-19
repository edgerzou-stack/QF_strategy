#!/usr/bin/env python3
import argparse
from datetime import date, timedelta
import json
import sys
import time
from typing import Optional

import akshare as ak
import pandas as pd
import requests

AUTO_REPORT_LOOKBACK = 4
QUARTER_ENDS = ((3, 31), (6, 30), (9, 30), (12, 31))
ANNUAL_REPORT_LOOKBACK = 8
LONG_TERM_CAGR_YEARS = 3
DIVIDEND_TTM_DAYS = 365


def to_secid(code: str) -> str:
    if code.startswith(("600", "601", "603", "605", "688", "689")):
        return "1." + code
    return "0." + code


def fetch_quote_snapshot(codes: list[str]) -> pd.DataFrame:
    if not codes:
        return pd.DataFrame(
            columns=["股票代码", "股票简称", "最新价", "PE", "PB", "总市值"]
        )

    session = requests.Session()
    session.headers.update(
        {"User-Agent": "Mozilla/5.0", "Referer": "https://quote.eastmoney.com/"}
    )
    url = "https://push2delay.eastmoney.com/api/qt/ulist.np/get"
    rows = []
    for i in range(0, len(codes), 200):
        batch = codes[i : i + 200]
        secids = ",".join(to_secid(code) for code in batch)
        resp = session.get(
            url,
            params={"secids": secids, "fields": "f12,f14,f2,f20,f23,f9,f115"},
            timeout=20,
        )
        resp.raise_for_status()
        rows.extend(((resp.json().get("data") or {}).get("diff") or []))
        time.sleep(0.03)
    df = pd.DataFrame(rows).rename(
        columns={
            "f12": "股票代码",
            "f14": "股票简称",
            "f2": "最新价_raw",
            "f20": "总市值",
            "f23": "PB_raw",
            "f9": "PE_dynamic_raw",
            "f115": "PE_ttm_raw",
        }
    )
    df["股票代码"] = df["股票代码"].astype(str).str.zfill(6)
    df["最新价"] = pd.to_numeric(df["最新价_raw"], errors="coerce")
    df["最新价"] = df["最新价"].where(
        ~(df["最新价"].notna() & (df["最新价"] % 1 == 0)), df["最新价"] / 100
    )
    df["PE"] = pd.to_numeric(df["PE_ttm_raw"], errors="coerce")
    pe_dynamic = pd.to_numeric(df["PE_dynamic_raw"], errors="coerce")
    df["PE"] = df["PE"].where(~df["PE"].isna(), pe_dynamic)
    df["PE"] = df["PE"].where(
        ~((df["PE"].abs() >= 200) & (df["PE"] % 1 == 0)), df["PE"] / 100
    )
    df["PB"] = pd.to_numeric(df["PB_raw"], errors="coerce")
    df["PB"] = df["PB"].where(
        ~((df["PB"].abs() >= 20) & (df["PB"] % 1 == 0)), df["PB"] / 100
    )
    df["总市值"] = pd.to_numeric(df["总市值"], errors="coerce")
    return df[["股票代码", "股票简称", "最新价", "PE", "PB", "总市值"]]


def calculate_ttm_dividend_yield_for_code(
    symbol: str, as_of_date: date, latest_price: Optional[float]
) -> Optional[float]:
    if latest_price is None or pd.isna(latest_price):
        return None
    latest_price = float(latest_price)
    if latest_price <= 0:
        return None

    try:
        dividend_df = ak.stock_dividend_cninfo(symbol=symbol)
    except Exception:
        return None

    if dividend_df.empty:
        return None

    cutoff_date = as_of_date - timedelta(days=DIVIDEND_TTM_DAYS)
    dividend_df = dividend_df.copy()
    dividend_df["派息日"] = pd.to_datetime(dividend_df["派息日"], errors="coerce").dt.date
    dividend_df["除权日"] = pd.to_datetime(dividend_df["除权日"], errors="coerce").dt.date
    dividend_df["派息比例"] = pd.to_numeric(dividend_df["派息比例"], errors="coerce")

    effective_date = dividend_df["派息日"].where(dividend_df["派息日"].notna(), dividend_df["除权日"])
    dividend_df = dividend_df.assign(生效日期=effective_date)
    dividend_df = dividend_df[
        dividend_df["生效日期"].notna()
        & (dividend_df["生效日期"] <= as_of_date)
        & (dividend_df["生效日期"] > cutoff_date)
        & dividend_df["派息比例"].notna()
        & (dividend_df["派息比例"] > 0)
    ].copy()

    if dividend_df.empty:
        return None

    # `派息比例` is cash dividend per 10 shares in CNY.
    dividend_per_share = dividend_df["派息比例"].sum() / 10.0
    return dividend_per_share / latest_price * 100.0


def load_ttm_dividend_yield_table(
    as_of_date: date,
    quote_df: pd.DataFrame,
    target_codes: Optional[list[str]] = None,
) -> pd.DataFrame:
    if quote_df.empty:
        return pd.DataFrame(columns=["股票代码", "TTM股息率"])

    base = quote_df[["股票代码", "最新价"]].copy()
    if target_codes is not None:
        base = base[base["股票代码"].isin(target_codes)].copy()

    rows = []
    for _, row in base.iterrows():
        rows.append(
            {
                "股票代码": row["股票代码"],
                "TTM股息率": calculate_ttm_dividend_yield_for_code(
                    symbol=row["股票代码"],
                    as_of_date=as_of_date,
                    latest_price=row["最新价"],
                ),
            }
        )
    return pd.DataFrame(rows)


def load_code_name_table() -> pd.DataFrame:
    codes = ak.stock_info_a_code_name()[["code", "name"]].drop_duplicates().copy()
    codes["code"] = codes["code"].astype(str).str.zfill(6)
    codes["name"] = codes["name"].astype(str).str.strip()
    return codes.rename(columns={"code": "股票代码", "name": "股票简称"})


def build_quote_table(target_codes: Optional[list[str]] = None) -> pd.DataFrame:
    code_name_df = load_code_name_table()
    if target_codes is None:
        base = code_name_df.copy()
    else:
        base = code_name_df[code_name_df["股票代码"].isin(target_codes)].copy()

    quote = fetch_quote_snapshot(base["股票代码"].tolist()).drop(
        columns=["股票简称"], errors="ignore"
    )
    merged = base.merge(quote, on="股票代码", how="left")
    merged["总市值(亿元)"] = pd.to_numeric(merged["总市值"], errors="coerce") / 1e8
    merged["估值公式值"] = merged["PE"] * (merged["PB"] - 1.0) / merged["PB"]
    merged["估值公式值"] = merged["估值公式值"].where(
        pd.notna(merged["PE"]) & pd.notna(merged["PB"]) & (merged["PB"] != 0)
    )
    return merged


def infer_candidate_report_dates(
    as_of_date: date, lookback: int = AUTO_REPORT_LOOKBACK
) -> list[str]:
    report_dates = []
    year = as_of_date.year

    while len(report_dates) < lookback:
        for month, day_in_month in reversed(QUARTER_ENDS):
            report_end = date(year, month, day_in_month)
            if report_end <= as_of_date:
                report_dates.append(report_end.strftime("%Y%m%d"))
                if len(report_dates) >= lookback:
                    break
        year -= 1

    return report_dates


def load_financial_tables(report_date: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    yjbb = ak.stock_yjbb_em(date=report_date)[
        [
            "股票代码",
            "股票简称",
            "营业总收入-营业总收入",
            "营业总收入-同比增长",
            "净利润-净利润",
            "净利润-同比增长",
            "最新公告日期",
        ]
    ].copy()
    yjbb["股票代码"] = yjbb["股票代码"].astype(str).str.zfill(6)
    yjbb["最新公告日期"] = pd.to_datetime(yjbb["最新公告日期"], errors="coerce").dt.date

    zcfz = ak.stock_zcfz_em(date=report_date)[
        ["股票代码", "股票简称", "资产负债率", "公告日期"]
    ].copy()
    zcfz["股票代码"] = zcfz["股票代码"].astype(str).str.zfill(6)
    zcfz["公告日期"] = pd.to_datetime(zcfz["公告日期"], errors="coerce").dt.date
    return yjbb, zcfz


def infer_candidate_annual_report_dates(
    as_of_date: date, lookback: int = ANNUAL_REPORT_LOOKBACK
) -> list[str]:
    dates = []
    year = as_of_date.year
    while len(dates) < lookback:
        annual_end = date(year, 12, 31)
        if annual_end <= as_of_date:
            dates.append(annual_end.strftime("%Y%m%d"))
        year -= 1
    return dates


def load_dynamic_cagr_table(
    as_of_date: date,
    target_codes: Optional[list[str]] = None,
) -> pd.DataFrame:
    annual_report_dates = infer_candidate_annual_report_dates(as_of_date)
    frames = []

    for report_date in annual_report_dates:
        yjbb = ak.stock_yjbb_em(date=report_date)[
            [
                "股票代码",
                "股票简称",
                "营业总收入-营业总收入",
                "营业总收入-同比增长",
                "净利润-净利润",
                "净利润-同比增长",
                "最新公告日期",
            ]
        ].copy()
        yjbb["股票代码"] = yjbb["股票代码"].astype(str).str.zfill(6)
        yjbb["最新公告日期"] = pd.to_datetime(yjbb["最新公告日期"], errors="coerce").dt.date
        yjbb["营业总收入-营业总收入"] = pd.to_numeric(
            yjbb["营业总收入-营业总收入"], errors="coerce"
        )
        yjbb["营业总收入-同比增长"] = pd.to_numeric(
            yjbb["营业总收入-同比增长"], errors="coerce"
        )
        yjbb["净利润-净利润"] = pd.to_numeric(yjbb["净利润-净利润"], errors="coerce")
        yjbb["净利润-同比增长"] = pd.to_numeric(
            yjbb["净利润-同比增长"], errors="coerce"
        )

        if target_codes is not None:
            yjbb = yjbb[yjbb["股票代码"].isin(target_codes)].copy()

        yjbb = yjbb[
            yjbb["最新公告日期"].notna() & (yjbb["最新公告日期"] <= as_of_date)
        ].copy()
        if yjbb.empty:
            continue

        yjbb["年报期末"] = report_date
        yjbb["年报年份"] = int(report_date[:4])
        frames.append(yjbb)

    if not frames:
        return pd.DataFrame(
            columns=[
                "股票代码",
                "CAGR终点年报",
                "CAGR起点年报",
                "3年连续双增长",
                "3年平均净利率",
                "3年营收CAGR",
                "3年净利润CAGR",
            ]
        )

    annual = pd.concat(frames, ignore_index=True)
    annual = annual.sort_values(["股票代码", "年报年份"], ascending=[True, False])

    rows = []
    for code, grp in annual.groupby("股票代码", sort=False):
        grp = grp.drop_duplicates("年报年份", keep="first").copy()
        grp = grp.sort_values("年报年份", ascending=False).reset_index(drop=True)
        if grp.empty:
            continue

        end_row = grp.iloc[0]
        target_start_year = int(end_row["年报年份"]) - LONG_TERM_CAGR_YEARS
        start_candidates = grp[grp["年报年份"] == target_start_year]
        if start_candidates.empty:
            continue
        start_row = start_candidates.iloc[0]

        revenue_cagr = None
        if (
            pd.notna(start_row["营业总收入-营业总收入"])
            and pd.notna(end_row["营业总收入-营业总收入"])
            and start_row["营业总收入-营业总收入"] > 0
            and end_row["营业总收入-营业总收入"] > 0
        ):
            revenue_cagr = (
                (
                    end_row["营业总收入-营业总收入"]
                    / start_row["营业总收入-营业总收入"]
                )
                ** (1.0 / LONG_TERM_CAGR_YEARS)
                - 1.0
            ) * 100.0

        profit_cagr = None
        if (
            pd.notna(start_row["净利润-净利润"])
            and pd.notna(end_row["净利润-净利润"])
            and start_row["净利润-净利润"] > 0
            and end_row["净利润-净利润"] > 0
        ):
            profit_cagr = (
                (end_row["净利润-净利润"] / start_row["净利润-净利润"])
                ** (1.0 / LONG_TERM_CAGR_YEARS)
                - 1.0
            ) * 100.0

        avg_net_margin = None
        continuous_growth = False
        target_years = [int(end_row["年报年份"]) - i for i in range(LONG_TERM_CAGR_YEARS)]
        last_5_years_grp = grp[grp["年报年份"].isin(target_years)]
        if len(last_5_years_grp) == LONG_TERM_CAGR_YEARS:
            rev = last_5_years_grp["营业总收入-营业总收入"]
            prof = last_5_years_grp["净利润-净利润"]
            if (rev > 0).all() and prof.notna().all():
                margins = prof / rev * 100.0
                avg_net_margin = margins.mean()
            
            rev_yoy = last_5_years_grp["营业总收入-同比增长"]
            prof_yoy = last_5_years_grp["净利润-同比增长"]
            if rev_yoy.notna().all() and prof_yoy.notna().all():
                if (rev_yoy > 0).all() and (prof_yoy > 0).all():
                    continuous_growth = True

        rows.append(
            {
                "股票代码": code,
                "CAGR终点年报": str(end_row["年报期末"]),
                "CAGR起点年报": str(start_row["年报期末"]),
                "3年连续双增长": continuous_growth,
                "3年平均净利率": avg_net_margin,
                "3年营收CAGR": revenue_cagr,
                "3年净利润CAGR": profit_cagr,
            }
        )

    return pd.DataFrame(rows)


def load_financial_table_as_of(
    as_of_date: date,
    report_date: Optional[str] = None,
    target_codes: Optional[list[str]] = None,
) -> tuple[pd.DataFrame, list[str], str]:
    candidate_report_dates = (
        [report_date] if report_date else infer_candidate_report_dates(as_of_date)
    )
    frames = []

    for candidate in candidate_report_dates:
        yjbb, zcfz = load_financial_tables(candidate)

        if target_codes is not None:
            yjbb = yjbb[yjbb["股票代码"].isin(target_codes)].copy()
            zcfz = zcfz[zcfz["股票代码"].isin(target_codes)].copy()

        yjbb = yjbb[
            yjbb["最新公告日期"].notna() & (yjbb["最新公告日期"] <= as_of_date)
        ].copy()
        zcfz = zcfz[zcfz["公告日期"].notna() & (zcfz["公告日期"] <= as_of_date)].copy()

        merged = yjbb.merge(
            zcfz[["股票代码", "资产负债率", "公告日期"]], on="股票代码", how="inner"
        )
        if merged.empty:
            continue

        merged["财务报告期"] = candidate
        frames.append(
            merged[
                [
                    "股票代码",
                    "股票简称",
                    "财务报告期",
                    "营业总收入-营业总收入",
                    "营业总收入-同比增长",
                    "净利润-净利润",
                    "净利润-同比增长",
                    "资产负债率",
                    "最新公告日期",
                    "公告日期",
                ]
            ]
        )

    if not frames:
        empty = pd.DataFrame(
            columns=[
                "股票代码",
                "股票简称",
                "财务报告期",
                "营业总收入-营业总收入",
                "营业总收入-同比增长",
                "净利润-净利润",
                "净利润-同比增长",
                "资产负债率",
                "最新公告日期",
                "公告日期",
            ]
        )
        mode = "fixed_report_date" if report_date else "latest_disclosed_as_of_quote_date"
        return empty, candidate_report_dates, mode

    financial = pd.concat(frames, ignore_index=True)
    for col in ["营业总收入-营业总收入", "营业总收入-同比增长", "净利润-净利润", "净利润-同比增长", "资产负债率"]:
        financial[col] = pd.to_numeric(financial[col], errors="coerce")

    financial["财务报告期_dt"] = pd.to_datetime(
        financial["财务报告期"], format="%Y%m%d", errors="coerce"
    )
    financial = financial.sort_values(
        ["股票代码", "财务报告期_dt", "最新公告日期", "公告日期"],
        ascending=[True, False, False, False],
    ).drop_duplicates("股票代码", keep="first")
    financial = financial.drop(columns=["财务报告期_dt"])

    mode = "fixed_report_date" if report_date else "latest_disclosed_as_of_quote_date"
    return financial, candidate_report_dates, mode


def attach_latest_financial_fields(
    df: pd.DataFrame,
    as_of_date: date,
    report_date: Optional[str] = None,
) -> tuple[pd.DataFrame, list[str], str]:
    candidate_report_dates = [report_date] if report_date else infer_candidate_report_dates(
        as_of_date
    )
    financial_mode = (
        "fixed_report_date" if report_date else "latest_disclosed_as_of_quote_date"
    )
    if df.empty:
        result = df.copy()
        for col in [
            "财务报告期",
            "营业总收入-营业总收入",
            "营业总收入-同比增长",
            "净利润-净利润",
            "净利润-同比增长",
            "资产负债率",
            "最新公告日期",
            "公告日期",
        ]:
            result[col] = pd.Series(dtype="object")
        return result, candidate_report_dates, financial_mode

    financial, candidate_report_dates, financial_mode = load_financial_table_as_of(
        as_of_date=as_of_date,
        report_date=report_date,
        target_codes=df["股票代码"].tolist(),
    )
    merged = df.merge(
        financial[
            [
                "股票代码",
                "财务报告期",
                "营业总收入-营业总收入",
                "营业总收入-同比增长",
                "净利润-净利润",
                "净利润-同比增长",
                "资产负债率",
                "最新公告日期",
                "公告日期",
            ]
        ],
        on="股票代码",
        how="left",
    )
    return merged, candidate_report_dates, financial_mode


def attach_dynamic_cagr_fields(df: pd.DataFrame, as_of_date: date) -> pd.DataFrame:
    if df.empty:
        result = df.copy()
        for col in ["CAGR终点年报", "CAGR起点年报", "3年连续双增长", "3年平均净利率", "3年营收CAGR", "3年净利润CAGR"]:
            result[col] = pd.Series(dtype="object")
        return result

    cagr_table = load_dynamic_cagr_table(
        as_of_date=as_of_date,
        target_codes=df["股票代码"].tolist(),
    )
    return df.merge(
        cagr_table[
            ["股票代码", "CAGR终点年报", "CAGR起点年报", "3年连续双增长", "3年平均净利率", "3年营收CAGR", "3年净利润CAGR"]
        ],
        on="股票代码",
        how="left",
    )


def parse_holding_inputs(raw_holdings: Optional[list[str]]) -> list[str]:
    holdings = []
    for raw in raw_holdings or []:
        for item in str(raw).split(","):
            item = item.strip()
            if item:
                holdings.append(item)
    return holdings


def resolve_holdings(
    holding_inputs: list[str], code_name_df: pd.DataFrame
) -> tuple[pd.DataFrame, list[dict]]:
    resolved_rows = []
    unresolved = []
    seen_codes = set()

    for item in holding_inputs:
        digits = "".join(ch for ch in item if ch.isdigit())
        if len(digits) == 6:
            matches = code_name_df[code_name_df["股票代码"] == digits]
        else:
            matches = code_name_df[code_name_df["股票简称"] == item]

        if len(matches) == 1:
            row = matches.iloc[0]
            code = row["股票代码"]
            if code in seen_codes:
                continue
            seen_codes.add(code)
            resolved_rows.append(
                {"输入": item, "股票代码": code, "股票简称": row["股票简称"]}
            )
        elif len(matches) == 0:
            unresolved.append(
                {
                    "输入": item,
                    "状态": "unresolved",
                    "原因": "未找到精确匹配的股票代码或简称",
                }
            )
        else:
            unresolved.append(
                {
                    "输入": item,
                    "状态": "ambiguous",
                    "原因": "匹配到多个同名股票，请改用6位股票代码",
                }
            )

    resolved = pd.DataFrame(resolved_rows)
    if resolved.empty:
        resolved = pd.DataFrame(columns=["输入", "股票代码", "股票简称"])
    return resolved, unresolved


def build_merged_table(
    quote_snapshot_date: date,
    report_date: Optional[str] = None,
    target_codes: Optional[list[str]] = None,
) -> tuple[pd.DataFrame, list[str], str]:
    quote_only = build_quote_table(target_codes=target_codes)
    with_financial, candidate_report_dates, financial_mode = attach_latest_financial_fields(
        quote_only,
        as_of_date=quote_snapshot_date,
        report_date=report_date,
    )
    merged = attach_dynamic_cagr_fields(with_financial, as_of_date=quote_snapshot_date)
    return merged, candidate_report_dates, financial_mode


def passes_valuation_formula(row: pd.Series, max_value: float) -> bool:
    value = row["估值公式值"]
    return pd.notna(value) and float(value) < max_value


def filter_by_market_thresholds(df: pd.DataFrame, args: argparse.Namespace) -> pd.DataFrame:
    if df.empty:
        return df.copy()
    mask = (
        df["估值公式值"].notna()
        & (df["估值公式值"] < args.valuation_formula_max)
        & df["总市值"].notna()
        & (df["总市值"] > args.market_cap_min_yi * 1e8)
    )
    return df[mask].copy()


def filter_by_financial_thresholds(
    df: pd.DataFrame, args: argparse.Namespace
) -> pd.DataFrame:
    if df.empty:
        return df.copy()
    mask = (
        df["资产负债率"].notna()
        & (df["资产负债率"] < args.debt_ratio_max)
    )
    return df[mask].copy()


def filter_by_cagr_thresholds(df: pd.DataFrame, args: argparse.Namespace) -> pd.DataFrame:
    if df.empty:
        return df.copy()
    mask = (
        df["3年平均净利率"].notna()
        & (df["3年平均净利率"] > args.avg_net_profit_margin_min)
        & df["3年净利润CAGR"].notna()
        & (df["3年净利润CAGR"] > args.profit_cagr_min)
    )
    if args.require_continuous_growth:
        mask = mask & (df["3年连续双增长"] == True)
    return df[mask].copy()


def filter_by_dividend_thresholds(
    df: pd.DataFrame, args: argparse.Namespace
) -> pd.DataFrame:
    if df.empty:
        return df.copy()
    mask = df["TTM股息率"].notna() & (df["TTM股息率"] > args.dividend_yield_min)
    return df[mask].copy()


def passes_thresholds(row: pd.Series, args: argparse.Namespace) -> bool:
    return (
        passes_valuation_formula(row, args.valuation_formula_max)
        and pd.notna(row["TTM股息率"])
        and row["TTM股息率"] > args.dividend_yield_min
        and pd.notna(row["总市值"])
        and row["总市值"] > args.market_cap_min_yi * 1e8
        and pd.notna(row["3年平均净利率"])
        and row["3年平均净利率"] > args.avg_net_profit_margin_min
        and pd.notna(row["3年净利润CAGR"])
        and row["3年净利润CAGR"] > args.profit_cagr_min
        and pd.notna(row["资产负债率"])
        and row["资产负债率"] < args.debt_ratio_max
    )


def passes_non_dividend_thresholds(row: pd.Series, args: argparse.Namespace) -> bool:
    return (
        passes_valuation_formula(row, args.valuation_formula_max)
        and pd.notna(row["总市值"])
        and row["总市值"] > args.market_cap_min_yi * 1e8
        and pd.notna(row["3年平均净利率"])
        and row["3年平均净利率"] > args.avg_net_profit_margin_min
        and pd.notna(row["3年净利润CAGR"])
        and row["3年净利润CAGR"] > args.profit_cagr_min
        and pd.notna(row["资产负债率"])
        and row["资产负债率"] < args.debt_ratio_max
    )


def filter_by_thresholds(df: pd.DataFrame, args: argparse.Namespace) -> pd.DataFrame:
    return filter_by_dividend_thresholds(
        filter_by_cagr_thresholds(
            filter_by_financial_thresholds(
                filter_by_market_thresholds(df, args),
                args,
            ),
            args,
        ),
        args,
    )


def filter_by_non_dividend_thresholds(
    df: pd.DataFrame, args: argparse.Namespace
) -> pd.DataFrame:
    return filter_by_cagr_thresholds(
        filter_by_financial_thresholds(
            filter_by_market_thresholds(df, args),
            args,
        ),
        args,
    )


def attach_ttm_dividend_yield(
    df: pd.DataFrame, as_of_date: date
) -> pd.DataFrame:
    if df.empty:
        result = df.copy()
        result["TTM股息率"] = pd.Series(dtype="float64")
        return result

    dividend_ttm = load_ttm_dividend_yield_table(
        as_of_date=as_of_date,
        quote_df=df[["股票代码", "最新价"]],
        target_codes=df["股票代码"].tolist(),
    )
    return df.merge(dividend_ttm, on="股票代码", how="left")


def threshold_payload(args: argparse.Namespace) -> dict:
    return {
        "valuation_formula_max": args.valuation_formula_max,
        "valuation_formula_definition": "(总市值 - 总市值 / PB) / (总市值 / PE)",
        "valuation_formula_equivalent": "PE * (PB - 1) / PB",
        "dividend_yield_min": args.dividend_yield_min,
        "dividend_yield_basis": "TTM_dividend_yield_from_last_12_months_cash_dividend",
        "market_cap_min_yi": args.market_cap_min_yi,
        "avg_net_profit_margin_min": args.avg_net_profit_margin_min,
        "require_continuous_growth": args.require_continuous_growth,
        "profit_cagr_min": args.profit_cagr_min,
        "long_term_cagr_years": LONG_TERM_CAGR_YEARS,
        "debt_ratio_max": args.debt_ratio_max,
    }


def output_columns(df: pd.DataFrame) -> pd.DataFrame:
    return df[
        [
            "股票代码",
            "股票简称",
            "财务报告期",
            "营业总收入-营业总收入",
            "净利润-净利润",
            "PE",
            "PB",
            "估值公式值",
            "TTM股息率",
            "总市值(亿元)",
            "CAGR终点年报",
            "CAGR起点年报",
            "3年连续双增长",
            "3年平均净利率",
            "3年营收CAGR",
            "3年净利润CAGR",
            "资产负债率",
        ]
    ].sort_values(["PB", "TTM股息率"], ascending=[True, False])


def number_or_none(value) -> Optional[float]:
    if pd.isna(value):
        return None
    return round(float(value), 4)


def string_or_none(value) -> Optional[str]:
    if pd.isna(value):
        return None
    return str(value)


def evaluate_holding(row: pd.Series, args: argparse.Namespace, user_input: str) -> dict:
    failed_rules = []

    checks = [
        (
            "估值公式值",
            f"(总市值 - 总市值 / PB) / (总市值 / PE) < {args.valuation_formula_max}",
            row["估值公式值"],
            lambda x: x < args.valuation_formula_max,
        ),
        (
            "TTM股息率",
            f"TTM股息率 > {args.dividend_yield_min}%",
            row["TTM股息率"],
            lambda x: x > args.dividend_yield_min,
        ),
        (
            "总市值(亿元)",
            f"总市值 > {args.market_cap_min_yi}亿",
            row["总市值(亿元)"],
            lambda x: x > args.market_cap_min_yi,
        ),
        (
            "3年平均净利率",
            f"过去3年平均净利率 > {args.avg_net_profit_margin_min}%",
            row["3年平均净利率"],
            lambda x: x > args.avg_net_profit_margin_min,
        ),
        (
            "3年净利润CAGR",
            f"过去3年净利润年复合增长率 > {args.profit_cagr_min}%",
            row["3年净利润CAGR"],
            lambda x: x > args.profit_cagr_min,
        ),
        (
            "资产负债率",
            f"资产负债率 < {args.debt_ratio_max}%",
            row["资产负债率"],
            lambda x: x < args.debt_ratio_max,
        ),
    ]

    if args.require_continuous_growth:
        checks.append(
            (
                "3年连续双增长",
                "过去3年每一年的营收和净利润同比增长 > 0",
                1.0 if row.get("3年连续双增长") else 0.0,
                lambda x: x == 1.0,
            )
        )

    for field, rule_text, value, rule_fn in checks:
        if pd.isna(value):
            failed_rules.append(
                {"字段": field, "规则": rule_text, "当前值": None, "原因": "缺少最新数据"}
            )
        elif not rule_fn(float(value)):
            failed_rules.append(
                {"字段": field, "规则": rule_text, "当前值": round(float(value), 4)}
            )

    passed = not failed_rules
    return {
        "输入": user_input,
        "股票代码": row["股票代码"],
        "股票简称": row["股票简称"],
        "财务报告期": string_or_none(row.get("财务报告期")),
        "满足规则": passed,
        "操作建议": "继续持有" if passed else "卖出提醒",
        "当前指标": {
            "财务报告期": string_or_none(row.get("财务报告期")),
            "营业总收入": number_or_none(row["营业总收入-营业总收入"]),
            "净利润": number_or_none(row["净利润-净利润"]),
            "PE": number_or_none(row["PE"]),
            "PB": number_or_none(row["PB"]),
            "估值公式值": number_or_none(row["估值公式值"]),
            "TTM股息率": number_or_none(row["TTM股息率"]),
            "总市值(亿元)": number_or_none(row["总市值(亿元)"]),
            "CAGR终点年报": string_or_none(row.get("CAGR终点年报")),
            "CAGR起点年报": string_or_none(row.get("CAGR起点年报")),
            "3年连续双增长": row.get("3年连续双增长"),
            "3年平均净利率": number_or_none(row["3年平均净利率"]),
            "3年营收CAGR": number_or_none(row["3年营收CAGR"]),
            "3年净利润CAGR": number_or_none(row["3年净利润CAGR"]),
            "资产负债率": number_or_none(row["资产负债率"]),
        },
        "不满足条件": failed_rules,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Screen A-share stocks by factor rules.")
    parser.add_argument(
        "--report-date",
        help=(
            "Optional fixed report period end, e.g. 20260331. "
            "If omitted, auto-pick each stock's latest disclosed common financial report "
            "as of today's quote snapshot."
        ),
    )
    parser.add_argument("--valuation-formula-max", type=float, default=10.0)
    parser.add_argument("--dividend-yield-min", type=float, default=3.0)
    parser.add_argument("--market-cap-min-yi", type=float, default=100.0)
    parser.add_argument("--avg-net-profit-margin-min", type=float, default=5.0)
    parser.add_argument("--require-continuous-growth", action="store_true")
    parser.add_argument("--profit-cagr-min", type=float, default=5.0)
    parser.add_argument("--debt-ratio-max", type=float, default=50.0)
    parser.add_argument(
        "--output-file",
        help="Optional JSON output file path. If omitted, print to stdout.",
    )
    parser.add_argument(
        "--holding",
        action="append",
        help="Holding stock code or short name; repeat or pass comma-separated values",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()

    quote_snapshot_date = date.today()
    snapshot_date = quote_snapshot_date.isoformat()
    holdings = parse_holding_inputs(args.holding)

    if holdings:
        code_name_df = load_code_name_table()
        resolved_holdings, unresolved_holdings = resolve_holdings(holdings, code_name_df)
        quote_stage = build_quote_table(
            target_codes=resolved_holdings["股票代码"].tolist(),
        )
        with_financial, candidate_report_dates, financial_mode = attach_latest_financial_fields(
            quote_stage,
            as_of_date=quote_snapshot_date,
            report_date=args.report_date,
        )
        with_cagr = attach_dynamic_cagr_fields(with_financial, as_of_date=quote_snapshot_date)
        merged = attach_ttm_dividend_yield(with_cagr, quote_snapshot_date)
        holding_lookup = {
            row["股票代码"]: row["输入"]
            for _, row in resolved_holdings.iterrows()
        }

        checks = []
        for _, row in merged.sort_values("股票代码").iterrows():
            checks.append(evaluate_holding(row, args, holding_lookup[row["股票代码"]]))

        payload = {
            "mode": "holding_check",
            "snapshot_date": snapshot_date,
            "financial_as_of_date": snapshot_date,
            "financial_selection_mode": financial_mode,
            "candidate_report_dates": candidate_report_dates,
            "report_date": args.report_date,
            "thresholds": threshold_payload(args),
            "check_count": int(len(checks)),
            "checks": checks,
            "unresolved_holdings": unresolved_holdings,
        }
    else:
        quote_stage = build_quote_table()
        market_stage = filter_by_market_thresholds(quote_stage, args)
        with_financial, candidate_report_dates, financial_mode = attach_latest_financial_fields(
            market_stage,
            as_of_date=quote_snapshot_date,
            report_date=args.report_date,
        )
        financial_stage = filter_by_financial_thresholds(with_financial, args)
        with_cagr = attach_dynamic_cagr_fields(financial_stage, as_of_date=quote_snapshot_date)
        cagr_stage = filter_by_cagr_thresholds(with_cagr, args)
        with_dividend = attach_ttm_dividend_yield(cagr_stage, quote_snapshot_date)
        result = output_columns(filter_by_dividend_thresholds(with_dividend, args))
        payload = {
            "mode": "screen",
            "snapshot_date": snapshot_date,
            "financial_as_of_date": snapshot_date,
            "financial_selection_mode": financial_mode,
            "candidate_report_dates": candidate_report_dates,
            "report_date": args.report_date,
            "thresholds": threshold_payload(args),
            "stage_counts": {
                "quote_stage": int(len(quote_stage)),
                "market_stage": int(len(market_stage)),
                "financial_stage": int(len(financial_stage)),
                "cagr_stage": int(len(cagr_stage)),
                "final_stage": int(len(result)),
            },
            "count": int(len(result)),
            "results": result.to_dict(orient="records"),
        }

    if args.output_file:
        with open(args.output_file, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
            f.write("\n")
    else:
        json.dump(payload, sys.stdout, ensure_ascii=False, indent=2)
        sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
