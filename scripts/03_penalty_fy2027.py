"""
03_penalty_fy2027.py
Rebuilds the CMS FY 2027 HRRP payment reduction from the Supplemental Data File,
checks it against CMS's official numbers, and splits each Kettering hospital's
penalty into condition-level contributions.

Data: data/raw/FY2027_HRRP_Supplemental_File.xlsx
      (FY 2027 IPPS/LTCH PPS Final Rule, discharges 7/1/2023 - 6/30/2025,
       Medicare FFS + Medicare Advantage)

CMS formula (from the Supplemental File variable descriptions and the
FY 2027 HRRP methodology infographic):

    payment reduction = min( 3%,  neutrality modifier x
                             SUM over penalized measures of
                             DRG payment ratio x (ERR - peer group median ERR) )

    A measure is "penalized" (penalty indicator = Y) when it has 25+ eligible
    discharges AND its ERR is above its peer group median.

Run from the project folder:
    python scripts/03_penalty_fy2027.py

Outputs:
    data/clean/fy2027_measures_long.csv     one row per hospital x condition (all U.S.)
    data/clean/fy2027_hospital_penalty.csv  one row per hospital (all U.S.)
"""

from pathlib import Path
import pandas as pd

PROJECT = Path(__file__).resolve().parent.parent
RAW = PROJECT / "data" / "raw"
CLEAN = PROJECT / "data" / "clean"
CLEAN.mkdir(parents=True, exist_ok=True)

SUPP_FILE = RAW / "FY2027_HRRP_Supplemental_File.xlsx"
MAPPING_FILE = RAW / "system_mapping.csv"
GENERAL_FILE = RAW / "Hospital_General_Information.csv"

# ---------------------------------------------------------------
# 1. Load. Row 1 is a title, so headers are on row 2 (header=1).
#    "." means "not available" in this file, so treat it as missing.
# ---------------------------------------------------------------
raw = pd.read_excel(SUPP_FILE, sheet_name="FR FY 2027", header=1, dtype=str, na_values=["."])
raw.columns = raw.columns.str.strip()

# Drop the "End of worksheet" footer row: keep only real 6-character CCNs
raw["Hospital CCN"] = raw["Hospital CCN"].str.strip()
raw = raw[raw["Hospital CCN"].str.len() == 6].copy()
print(f"Hospitals in FY 2027 file: {len(raw):,}")

# ---------------------------------------------------------------
# 2. Hospital-level columns
# ---------------------------------------------------------------
hosp = pd.DataFrame({
    "facility_id": raw["Hospital CCN"],
    "cms_payment_adjustment_factor": pd.to_numeric(raw["Payment adjustment factor"]),
    "cms_payment_reduction_pct": pd.to_numeric(raw["Payment reduction percentage"]),
    "dual_proportion": pd.to_numeric(raw["Dual proportion"]),
    "peer_group": pd.to_numeric(raw["Peer group assignment"]),
    "neutrality_modifier": pd.to_numeric(raw["Neutrality modifier"]),
})

# ---------------------------------------------------------------
# 3. Reshape the 6 conditions from wide (30 columns) to long (one row each)
# ---------------------------------------------------------------
CONDITIONS = {
    "AMI": "AMI (Heart Attack)",
    "COPD": "COPD",
    "HF": "Heart Failure",
    "pneumonia": "Pneumonia",
    "CABG": "CABG (Bypass Surgery)",
    "THA/TKA": "Hip/Knee Replacement",
}

parts = []
for code, name in CONDITIONS.items():
    part = pd.DataFrame({
        "facility_id": raw["Hospital CCN"],
        "condition": name,
        "eligible_discharges": pd.to_numeric(raw[f"Number of eligible discharges for {code}"]),
        "err": pd.to_numeric(raw[f"ERR for {code}"]),
        "peer_median_err": pd.to_numeric(raw[f"Peer group median ERR for {code}"]),
        "penalty_indicator": raw[f"Penalty indicator for {code}"].str.strip(),
        "drg_payment_ratio": pd.to_numeric(raw[f"DRG payment ratio for {code}"]),
    })
    parts.append(part)

long = pd.concat(parts, ignore_index=True)
long = long.merge(hosp[["facility_id", "neutrality_modifier", "peer_group"]], on="facility_id")

# ---------------------------------------------------------------
# 4. Each measure's contribution to the payment reduction
#    Only penalized measures (indicator = Y) contribute.
# ---------------------------------------------------------------
long["err_gap_vs_peer"] = long["err"] - long["peer_median_err"]
long["penalized"] = long["penalty_indicator"].eq("Y")
long["reduction_contribution"] = 0.0
mask = long["penalized"]
long.loc[mask, "reduction_contribution"] = (
    long.loc[mask, "drg_payment_ratio"]
    * long.loc[mask, "err_gap_vs_peer"]
    * long.loc[mask, "neutrality_modifier"]
)

# ---------------------------------------------------------------
# 5. Rebuild each hospital's total payment reduction and compare with CMS
# ---------------------------------------------------------------
rebuilt = long.groupby("facility_id")["reduction_contribution"].sum().rename("rebuilt_reduction_uncapped")
hosp = hosp.merge(rebuilt, on="facility_id", how="left")
hosp["rebuilt_reduction_pct"] = hosp["rebuilt_reduction_uncapped"].clip(upper=0.03)
hosp["capped_at_3pct"] = hosp["rebuilt_reduction_uncapped"] > 0.03

# CMS rounds the published value to 4 decimals, so compare at that precision
hosp["matches_cms"] = (hosp["rebuilt_reduction_pct"].round(4) - hosp["cms_payment_reduction_pct"]).abs() <= 0.00011

match_rate = hosp["matches_cms"].mean()
print(f"\n=== VALIDATION: rebuilt penalty vs. CMS official ===")
print(f"Hospitals matching CMS (within rounding): {hosp['matches_cms'].sum():,} of {len(hosp):,} ({match_rate:.1%})")
if match_rate < 0.99:
    print("WARNING: formula does not reproduce CMS for some hospitals. Review before using results.")
    print(hosp.loc[~hosp["matches_cms"], ["facility_id", "cms_payment_reduction_pct", "rebuilt_reduction_pct"]].head(10))

# Share of each hospital's penalty that comes from each condition
long = long.merge(hosp[["facility_id", "rebuilt_reduction_uncapped"]], on="facility_id")
long["share_of_hospital_penalty"] = (
    long["reduction_contribution"] / long["rebuilt_reduction_uncapped"]
).where(long["rebuilt_reduction_uncapped"] > 0, 0)

# ---------------------------------------------------------------
# 6. Add names, state, and health system
# ---------------------------------------------------------------
general = pd.read_csv(GENERAL_FILE, dtype=str).rename(columns={
    "Facility ID": "facility_id", "Facility Name": "facility_name", "State": "state", "City/Town": "city"})
general = general[["facility_id", "facility_name", "state", "city"]]

mapping = pd.read_csv(MAPPING_FILE, dtype=str).rename(columns={
    "Facility ID": "facility_id", "Health System": "health_system"})
mapping = mapping[["facility_id", "health_system"]]

def add_labels(df):
    """Attach hospital name, state, city, and health system."""
    df = df.merge(general, on="facility_id", how="left").merge(mapping, on="facility_id", how="left")
    df["health_system"] = df["health_system"].fillna("Other")
    # The first 2 digits of a CCN are the state code (Ohio = 36). Use it when the name file has no match.
    df["state"] = df["state"].fillna(df["facility_id"].str[:2].map({"36": "OH"}))
    return df


hosp = add_labels(hosp)
long = add_labels(long)

long = long.drop(columns=["rebuilt_reduction_uncapped"])
long.to_csv(CLEAN / "fy2027_measures_long.csv", index=False)
hosp.to_csv(CLEAN / "fy2027_hospital_penalty.csv", index=False)

# ---------------------------------------------------------------
# 7. Kettering summary
# ---------------------------------------------------------------
kh = hosp[hosp["health_system"] == "Kettering Health"].sort_values("cms_payment_reduction_pct", ascending=False)
kl = long[long["health_system"] == "Kettering Health"]
oh = hosp[hosp["state"] == "OH"]

print("\n=== KETTERING: FY 2027 penalty by hospital ===")
print(kh[["facility_name", "peer_group", "cms_payment_reduction_pct", "rebuilt_reduction_pct", "matches_cms"]]
      .assign(cms_payment_reduction_pct=lambda d: (d.cms_payment_reduction_pct * 100).round(2).astype(str) + "%",
              rebuilt_reduction_pct=lambda d: (d.rebuilt_reduction_pct * 100).round(2).astype(str) + "%")
      .to_string(index=False))

print(f"\nOhio hospitals in file: {len(oh)} | median penalty: {oh['cms_payment_reduction_pct'].median()*100:.2f}% "
      f"| Kettering median: {kh['cms_payment_reduction_pct'].median()*100:.2f}%")

print("\n=== KETTERING: penalty contribution by condition (sum of percentage points across 7 hospitals) ===")
cond = (kl.groupby("condition")
          .agg(hospitals_penalized=("penalized", "sum"),
               hospitals_measured=("err", "count"),
               total_contribution=("reduction_contribution", "sum"))
          .sort_values("total_contribution", ascending=False))
cond["share_of_system_total"] = cond["total_contribution"] / cond["total_contribution"].sum()
cond["total_contribution"] = (cond["total_contribution"] * 100).round(3).astype(str) + " pts"
cond["share_of_system_total"] = (cond["share_of_system_total"] * 100).round(1).astype(str) + "%"
print(cond.to_string())

print("\n=== KETTERING: every penalized measure ===")
pen = kl[kl["penalized"]].sort_values("reduction_contribution", ascending=False)
print(pen[["facility_name", "condition", "eligible_discharges", "err", "peer_median_err",
           "err_gap_vs_peer", "drg_payment_ratio", "reduction_contribution"]]
      .round({"err": 4, "peer_median_err": 4, "err_gap_vs_peer": 4, "drg_payment_ratio": 4, "reduction_contribution": 5})
      .to_string(index=False))
