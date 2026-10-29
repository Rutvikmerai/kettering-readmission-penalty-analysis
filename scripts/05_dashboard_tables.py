"""
05_dashboard_tables.py
Builds the three tables the Power BI dashboard loads (a simple star schema).
Scope: all Ohio hospitals in the FY 2027 HRRP Supplemental File, so Kettering
can be compared with the rest of the state.

ALL DOLLAR FIGURES ARE ESTIMATES (see docs/decision_log.md, D7).

Inputs (from earlier scripts):
    data/clean/fy2027_hospital_penalty.csv
    data/clean/fy2027_measures_long.csv
    data/raw/Medicare_Inpatient_by_Provider_DY2024.csv

Run from the project folder:
    python scripts/05_dashboard_tables.py

Outputs (data/dashboard/):
    dim_hospital.csv    one row per Ohio hospital
    dim_condition.csv   one row per condition
    fact_measure.csv    one row per Ohio hospital x condition
"""

from pathlib import Path
import pandas as pd

PROJECT = Path(__file__).resolve().parent.parent
RAW = PROJECT / "data" / "raw"
CLEAN = PROJECT / "data" / "clean"
OUT = PROJECT / "data" / "dashboard"
OUT.mkdir(parents=True, exist_ok=True)

BASE_SHARE_LOW = 0.70   # same assumption as script 04 (D7)
BASE_SHARE_HIGH = 1.00

hosp = pd.read_csv(CLEAN / "fy2027_hospital_penalty.csv", dtype={"facility_id": str})
long = pd.read_csv(CLEAN / "fy2027_measures_long.csv", dtype={"facility_id": str})
pay = pd.read_csv(RAW / "Medicare_Inpatient_by_Provider_DY2024.csv", dtype=str, encoding="latin-1")
pay["facility_id"] = pay["Rndrng_Prvdr_CCN"].str.strip().str.zfill(6)
pay["medicare_payments_2024"] = pd.to_numeric(pay["Tot_Mdcr_Pymt_Amt"])
pay = pay[["facility_id", "medicare_payments_2024"]]

# ---------------------------------------------------------------
# 1. dim_hospital (Ohio only)
# ---------------------------------------------------------------
oh = hosp[hosp["state"] == "OH"].merge(pay, on="facility_id", how="left").copy()

# Friendly display names for Kettering (CMS uses old or long names)
DISPLAY = {
    "360079": "Kettering Health Main Campus",
    "360133": "Kettering Health Dayton",
    "360026": "Kettering Health Greene Memorial",
    "360132": "Kettering Health Hamilton",
    "360239": "Kettering Health Miamisburg",
    "360360": "Soin Medical Center",
    "360368": "Kettering Health Troy",
}
oh["display_name"] = oh["facility_id"].map(DISPLAY).fillna(oh["facility_name"].str.title())
oh["is_kettering"] = oh["health_system"].eq("Kettering Health")
oh["system_group"] = oh["is_kettering"].map({True: "Kettering Health", False: "Other Ohio"})
oh["is_penalized"] = oh["cms_payment_reduction_pct"] > 0
oh["est_penalty_low"] = oh["cms_payment_reduction_pct"] * oh["medicare_payments_2024"] * BASE_SHARE_LOW
oh["est_penalty_high"] = oh["cms_payment_reduction_pct"] * oh["medicare_payments_2024"] * BASE_SHARE_HIGH
oh["has_payment_data"] = oh["medicare_payments_2024"].notna()

dim_hospital = oh[[
    "facility_id", "display_name", "facility_name", "city", "health_system", "system_group",
    "is_kettering", "peer_group", "dual_proportion",
    "cms_payment_reduction_pct", "is_penalized", "capped_at_3pct",
    "medicare_payments_2024", "has_payment_data", "est_penalty_low", "est_penalty_high",
]].sort_values("display_name")

# ---------------------------------------------------------------
# 2. dim_condition
# ---------------------------------------------------------------
dim_condition = pd.DataFrame({
    "condition": ["Heart Failure", "AMI (Heart Attack)", "Pneumonia", "COPD",
                  "CABG (Bypass Surgery)", "Hip/Knee Replacement"],
    "condition_short": ["Heart Failure", "Heart Attack", "Pneumonia", "COPD", "Bypass Surgery", "Hip/Knee"],
    "condition_type": ["Medical", "Medical", "Medical", "Medical", "Surgical", "Surgical"],
    "sort_order": [1, 2, 3, 4, 5, 6],
})

# ---------------------------------------------------------------
# 3. fact_measure (Ohio hospital x condition)
# ---------------------------------------------------------------
f = long[long["facility_id"].isin(dim_hospital["facility_id"])].merge(
    dim_hospital[["facility_id", "est_penalty_low", "est_penalty_high"]], on="facility_id", how="left")

f["measured"] = f["err"].notna()
f["est_condition_dollars_low"] = f["share_of_hospital_penalty"] * f["est_penalty_low"]
f["est_condition_dollars_high"] = f["share_of_hospital_penalty"] * f["est_penalty_high"]

# For hospitals at the 3% cap, condition shares still sum to 100% of the capped
# penalty, so the split stays valid. No row is dropped.
fact_measure = f[[
    "facility_id", "condition", "measured", "eligible_discharges",
    "err", "peer_median_err", "err_gap_vs_peer", "penalty_indicator", "penalized",
    "drg_payment_ratio", "reduction_contribution", "share_of_hospital_penalty",
    "est_condition_dollars_low", "est_condition_dollars_high",
]]

# ---------------------------------------------------------------
# 4. Checks and save
# ---------------------------------------------------------------
assert dim_hospital["facility_id"].is_unique
assert len(fact_measure) == len(dim_hospital) * 6, "Each hospital should have 6 condition rows"
assert set(fact_measure["condition"]) == set(dim_condition["condition"])

kh_total = dim_hospital.loc[dim_hospital["is_kettering"], ["est_penalty_low", "est_penalty_high"]].sum()
kh_cond_total = fact_measure.merge(dim_hospital[["facility_id", "is_kettering"]])
kh_cond_total = kh_cond_total.loc[kh_cond_total["is_kettering"], ["est_condition_dollars_low", "est_condition_dollars_high"]].sum()
assert abs(kh_total["est_penalty_high"] - kh_cond_total["est_condition_dollars_high"]) < 1, \
    "Condition dollars do not add up to hospital dollars"

dim_hospital.to_csv(OUT / "dim_hospital.csv", index=False)
dim_condition.to_csv(OUT / "dim_condition.csv", index=False)
fact_measure.to_csv(OUT / "fact_measure.csv", index=False)

print(f"dim_hospital:  {len(dim_hospital)} Ohio hospitals ({dim_hospital['is_kettering'].sum()} Kettering)")
print(f"dim_condition: {len(dim_condition)} conditions")
print(f"fact_measure:  {len(fact_measure)} rows")
print(f"Kettering estimated penalty (estimate): ${kh_total['est_penalty_low']:,.0f} - ${kh_total['est_penalty_high']:,.0f}")
print(f"Ohio hospitals penalized: {dim_hospital['is_penalized'].sum()} of {len(dim_hospital)}")
print(f"Saved to {OUT}")
