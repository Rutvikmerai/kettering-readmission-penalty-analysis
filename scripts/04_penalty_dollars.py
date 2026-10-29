"""
04_penalty_dollars.py
Estimates FY 2027 HRRP penalty dollars for Kettering Health hospitals and
splits them by condition.

ALL DOLLAR FIGURES ARE ESTIMATES. See docs/decision_log.md (D7).

Inputs:
    data/clean/fy2027_hospital_penalty.csv   (from 03_penalty_fy2027.py)
    data/clean/fy2027_measures_long.csv      (from 03_penalty_fy2027.py)
    data/raw/Medicare_Inpatient_by_Provider_DY2024.csv
        (CMS "Medicare Inpatient Hospitals - by Provider", data year 2024)

Method:
    The penalty applies to Medicare FFS BASE OPERATING DRG payments only.
    The public file reports TOTAL Medicare payments, which also include
    add-ons (teaching/IME, safety-net/DSH, outliers, capital). So the base
    is shown as a range:
        high estimate = 100% of total Medicare payments (ceiling)
        low estimate  =  70% of total Medicare payments (assumption)
    Estimated penalty $ = payment reduction % x estimated base payments.
    2024 payments are used as a stand-in for FY 2027 volume.

Run from the project folder:
    python scripts/04_penalty_dollars.py

Outputs:
    data/clean/kettering_penalty_dollars_by_hospital.csv
    data/clean/kettering_penalty_dollars_by_condition.csv
"""

from pathlib import Path
import pandas as pd

PROJECT = Path(__file__).resolve().parent.parent
RAW = PROJECT / "data" / "raw"
CLEAN = PROJECT / "data" / "clean"

BASE_SHARE_LOW = 0.70    # assumption: base operating DRG share of total Medicare payments
BASE_SHARE_HIGH = 1.00   # ceiling: base payments cannot exceed total payments

# ---------------------------------------------------------------
# 1. Load
# ---------------------------------------------------------------
hosp = pd.read_csv(CLEAN / "fy2027_hospital_penalty.csv", dtype={"facility_id": str})
long = pd.read_csv(CLEAN / "fy2027_measures_long.csv", dtype={"facility_id": str})
pay = pd.read_csv(RAW / "Medicare_Inpatient_by_Provider_DY2024.csv", dtype=str, encoding="latin-1")

# The CMS export drops leading zeros from some CCNs (e.g. 10001 instead of 010001)
pay["facility_id"] = pay["Rndrng_Prvdr_CCN"].str.strip().str.zfill(6)
pay["medicare_discharges_2024"] = pd.to_numeric(pay["Tot_Dschrgs"])
pay["total_medicare_payments_2024"] = pd.to_numeric(pay["Tot_Mdcr_Pymt_Amt"])
pay = pay[["facility_id", "medicare_discharges_2024", "total_medicare_payments_2024"]]

# ---------------------------------------------------------------
# 2. Join payments to penalties
# ---------------------------------------------------------------
df = hosp.merge(pay, on="facility_id", how="left")
missing = df["total_medicare_payments_2024"].isna().sum()
print(f"Hospitals in penalty file: {len(df):,} | without 2024 payment data: {missing}")

df["est_base_payments_low"] = df["total_medicare_payments_2024"] * BASE_SHARE_LOW
df["est_base_payments_high"] = df["total_medicare_payments_2024"] * BASE_SHARE_HIGH
df["est_penalty_dollars_low"] = df["cms_payment_reduction_pct"] * df["est_base_payments_low"]
df["est_penalty_dollars_high"] = df["cms_payment_reduction_pct"] * df["est_base_payments_high"]

# ---------------------------------------------------------------
# 3. Kettering by hospital
# ---------------------------------------------------------------
kh = df[df["health_system"] == "Kettering Health"].copy()
assert len(kh) == 7, f"Expected 7 Kettering hospitals, found {len(kh)}"
assert kh["total_medicare_payments_2024"].notna().all(), "A Kettering hospital has no payment data"
assert not kh["capped_at_3pct"].any(), "A Kettering hospital hit the 3% cap; condition split needs adjusting"

kh = kh.sort_values("est_penalty_dollars_high", ascending=False)
by_hosp = kh[[
    "facility_id", "facility_name", "peer_group", "cms_payment_reduction_pct",
    "medicare_discharges_2024", "total_medicare_payments_2024",
    "est_penalty_dollars_low", "est_penalty_dollars_high",
]]
by_hosp.to_csv(CLEAN / "kettering_penalty_dollars_by_hospital.csv", index=False)

# ---------------------------------------------------------------
# 4. Kettering by condition
#    Each hospital's penalty $ is split by each condition's share of that
#    hospital's penalty (share_of_hospital_penalty, from script 03).
#    Valid because no Kettering hospital hits the 3% cap.
# ---------------------------------------------------------------
kl = long[long["health_system"] == "Kettering Health"].merge(
    kh[["facility_id", "est_penalty_dollars_low", "est_penalty_dollars_high"]], on="facility_id")
kl["cond_dollars_low"] = kl["share_of_hospital_penalty"] * kl["est_penalty_dollars_low"]
kl["cond_dollars_high"] = kl["share_of_hospital_penalty"] * kl["est_penalty_dollars_high"]

by_cond = (kl.groupby("condition")
             .agg(hospitals_penalized=("penalized", "sum"),
                  est_dollars_low=("cond_dollars_low", "sum"),
                  est_dollars_high=("cond_dollars_high", "sum"))
             .sort_values("est_dollars_high", ascending=False)
             .reset_index())
by_cond["share_of_system_dollars"] = by_cond["est_dollars_high"] / by_cond["est_dollars_high"].sum()
by_cond.to_csv(CLEAN / "kettering_penalty_dollars_by_condition.csv", index=False)

# Hospital x condition detail (used for the dashboard)
detail = kl[kl["penalized"]][["facility_name", "condition", "err", "peer_median_err",
                               "share_of_hospital_penalty", "cond_dollars_low", "cond_dollars_high"]]
detail = detail.sort_values("cond_dollars_high", ascending=False)
detail.to_csv(CLEAN / "kettering_penalty_dollars_detail.csv", index=False)

# ---------------------------------------------------------------
# 5. Print summary
# ---------------------------------------------------------------
def money(x):
    return f"${x:,.0f}"

print("\n=== ESTIMATED FY 2027 PENALTY BY HOSPITAL (estimate) ===")
show = by_hosp.copy()
show["penalty"] = (show["cms_payment_reduction_pct"] * 100).round(2).astype(str) + "%"
show["medicare_pay_2024"] = show["total_medicare_payments_2024"].map(money)
show["est_range"] = show["est_penalty_dollars_low"].map(money) + " - " + show["est_penalty_dollars_high"].map(money)
print(show[["facility_name", "penalty", "medicare_pay_2024", "est_range"]].to_string(index=False))
print(f"\nKETTERING SYSTEM TOTAL (estimate): "
      f"{money(by_hosp['est_penalty_dollars_low'].sum())} - {money(by_hosp['est_penalty_dollars_high'].sum())}")

print("\n=== ESTIMATED PENALTY DOLLARS BY CONDITION (estimate) ===")
show = by_cond.copy()
show["est_range"] = show["est_dollars_low"].map(money) + " - " + show["est_dollars_high"].map(money)
show["share"] = (show["share_of_system_dollars"] * 100).round(1).astype(str) + "%"
print(show[["condition", "hospitals_penalized", "est_range", "share"]].to_string(index=False))

print("\n=== TOP 5 HOSPITAL x CONDITION DRIVERS (estimate) ===")
top = detail.head(5).copy()
top["est_range"] = top["cond_dollars_low"].map(money) + " - " + top["cond_dollars_high"].map(money)
print(top[["facility_name", "condition", "est_range"]].to_string(index=False))

oh = df[(df["state"] == "OH") & df["total_medicare_payments_2024"].notna()]
print(f"\nContext: Ohio total estimated FY 2027 HRRP penalty (estimate): "
      f"{money(oh['est_penalty_dollars_low'].sum())} - {money(oh['est_penalty_dollars_high'].sum())} "
      f"across {len(oh)} hospitals")
