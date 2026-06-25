"""
Immo Eliza — Belgian Real-Estate Data Analysis
==============================================

Final consolidation script for the analysis project.

This single script:
    1. Loads the raw scraped dataset            (data/raw/properties_parsed.csv)
    2. Cleans it with the team DataCleaner       -> data/cleaned/properties_final.csv
    3. Generates EVERY team visual and saves     -> images/*.png

Run from the repository root:

    python main.py

All figures are produced with the non-interactive 'Agg' backend, so the
script runs head-less (no display needed) and is fully reproducible:
the CEO can re-run it after a small change and regenerate every image.

Team visuals included
---------------------
Cleaning / overview (Dan & Irene)
    overview_dashboard.png
    price_map_belgium.png
    q1_columns_to_drop.png
    q2_price_drivers.png
Data integrity (Irene)
    missing_values_per_column.png
Correlation & municipalities (Neha)
    correlation_heatmap.png
    municipality_prices.png
    municipality_prices_by_region.png
    municipality_median_by_region.png
    municipality_per_m2_by_region.png
Prestige, distributions & structure (Victor)
    prestige_price_distribution.png
    prestige_price_within_5km.png
    price_per_m2_vs_distance.png
    spearman_clustermap.png
    living_area_histogram.png
    qualitative_variables_grid.png
    quantitative_variables_grid.png
    price_per_m2_by_province_surface.png
"""

from __future__ import annotations

import warnings
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # head-less backend: save figures without a display
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np
import pandas as pd
import seaborn as sns

warnings.filterwarnings("ignore")
sns.set_theme(style="whitegrid")

# --------------------------------------------------------------------------- #
# Paths (everything is relative to this file, so the script is location-proof)
# --------------------------------------------------------------------------- #
BASE_DIR = Path(__file__).resolve().parent
RAW_CSV = BASE_DIR / "data" / "raw" / "properties_parsed.csv"
CLEANED_CSV = BASE_DIR / "data" / "cleaned" / "properties_final.csv"
IMAGES_DIR = BASE_DIR / "images"


def save(fig, name: str) -> None:
    """Save a figure to images/<name>.png and close it to free memory."""
    IMAGES_DIR.mkdir(parents=True, exist_ok=True)
    path = IMAGES_DIR / name
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  saved  images/{name}")


# =========================================================================== #
# 1. DATA CLEANING
# =========================================================================== #
class DataCleaner:
    """Loads the raw scraper CSV and produces a cleaned DataFrame.

    All cleaning knowledge (category orders, synonyms, geographic bounds,
    plausibility thresholds) lives here as class attributes, so there is a
    single place to update.
    """

    BOOL_COLS = [
        "furnished", "has_garage", "has_garden", "has_terrace",
        "has_elevator", "is_nearby_city_prestigious",
    ]
    PRESENCE_FLAGS = ["has_garage", "has_garden", "has_terrace", "has_elevator", "furnished"]

    EPC_ORDER = ["A++", "A+", "A", "B+", "B", "C", "D", "E+", "E", "F", "G"]
    STATE_ORDER = [
        "New", "Excellent", "Fully renovated", "Normal",
        "To renovate", "To restore", "Under construction", "To demolish",
    ]
    STATE_SYNONYMS = {"To be renovated": "To renovate"}
    KITCHEN_ORDER = ["Not equipped", "Partially equipped", "Fully equipped", "Super equipped"]

    # Geographic bounds of Belgium + max distance to accept a coordinate swap.
    BE_LAT = (49, 52)
    BE_LON = (2, 7)
    SWAP_MAX_KM = 25

    # Bedroom/area plausibility FLAG (review, not deletion).
    MIN_M2_PER_BEDROOM_SMALL = 9
    MIN_COMMON_AREA_M2 = 15

    # Hard floors for DELETION — physically impossible values only.
    HARD_MIN_PRICE = 19_900
    HARD_MIN_AREA = 10
    HARD_MIN_M2_PER_BEDROOM = 5
    MAX_BUILDING_YEAR = 2026

    URLS_TO_DROP = {
        "https://immovlan.be/en/real-estate/house/for-sale/sint-truiden",
        "https://immovlan.be/en/detail/master-house/for-sale/3540/herk-de-stad/rbv60505",
    }

    def __init__(self, path):
        self.path = path
        self.raw = pd.read_csv(path)  # untouched copy, useful for the Q1 audit
        self.df = None

    # ----- geographic helpers -----
    @staticmethod
    def _haversine(lat1, lon1, lat2, lon2):
        """Great-circle distance in km between two points (decimal degrees)."""
        R = 6371
        lat1, lon1, lat2, lon2 = map(np.radians, [lat1, lon1, lat2, lon2])
        a = np.sin((lat2 - lat1) / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin((lon2 - lon1) / 2) ** 2
        return 2 * R * np.arcsin(np.sqrt(a))

    def _postal_centroids(self, df):
        """Median lat/lon per postal code, from rows already inside Belgium."""
        valid = df["latitude"].between(*self.BE_LAT) & df["longitude"].between(*self.BE_LON)
        return df[valid].groupby("postal_code")[["latitude", "longitude"]].median()

    def _fix_swapped_coordinates(self, df):
        """Swap lat/lon only when it brings the point near its postal centroid."""
        cent = self._postal_centroids(df)

        lan_lon_present = df["latitude"].notna() & df["longitude"].notna()
        lan_lon_out_of_be = ~(
            df["latitude"].between(*self.BE_LAT) & df["longitude"].between(*self.BE_LON)
        )
        candidate = lan_lon_present & lan_lon_out_of_be

        df["coord_swapped"] = False
        df["coord_suspect"] = False

        clat = df["postal_code"].map(cent["latitude"])
        clon = df["postal_code"].map(cent["longitude"])
        distance_with_cent = self._haversine(df["longitude"], df["latitude"], clat, clon)

        cond_masq = candidate & (distance_with_cent < self.SWAP_MAX_KM)
        df.loc[cond_masq, "coord_swapped"] = True

        suspect_masq = candidate & ~cond_masq
        df.loc[suspect_masq, "coord_suspect"] = True

        # Vectorized lat/lon swap for confirmed rows
        df.loc[cond_masq, ["longitude", "latitude"]] = df.loc[
            cond_masq, ["latitude", "longitude"]
        ].values
        return df

    # ----- plausibility flag + deletion -----
    def _flag_suspect_bedroom_count(self, df):
        min_required_area = (
            df["bedrooms"] * self.MIN_M2_PER_BEDROOM_SMALL + self.MIN_COMMON_AREA_M2
        )
        df["bedroom_suspect"] = df["living_area_m2"] < min_required_area
        return df

    def _drop_impossible_rows(self, df):
        before = len(df)
        impossible_masq = (
            (df["price"] < self.HARD_MIN_PRICE)
            | (df["living_area_m2"] < self.HARD_MIN_AREA)
            | (df["living_area_m2"] < df["bedrooms"] * self.HARD_MIN_M2_PER_BEDROOM)
            | (df["building_year"] > self.MAX_BUILDING_YEAR)
        )
        df = df[~impossible_masq].copy()
        print(
            f"  dropped {before - len(df)} impossible rows "
            f"(price < {self.HARD_MIN_PRICE} EUR, area < {self.HARD_MIN_AREA} m2, "
            f"or < {self.HARD_MIN_M2_PER_BEDROOM} m2/bedroom)"
        )
        return df

    # ----- main entry -----
    def clean(self):
        """Run the full cleaning pipeline and return the cleaned DataFrame."""
        df = self.raw.copy()

        # 1) Drop useless columns (constant + duplicate).
        df = df.drop(columns=[c for c in ["price_type", "property_id"] if c in df.columns])

        # 2) Normalise the city slug.
        if "city" in df.columns:
            df["city"] = df["city"].str.replace("-", " ", regex=False).str.title()

        # 3) Building state: merge synonyms + ordered category.
        if "state_of_the_building" in df.columns:
            df["state_of_the_building"] = df["state_of_the_building"].replace(self.STATE_SYNONYMS)
            df["state_of_the_building"] = pd.Categorical(
                df["state_of_the_building"], categories=self.STATE_ORDER, ordered=True
            )

        # 4) EPC and kitchen as ordered categories.
        if "epc_score" in df.columns:
            df["epc_score"] = pd.Categorical(df["epc_score"], categories=self.EPC_ORDER, ordered=True)
        if "kitchen_equipped" in df.columns:
            df["kitchen_equipped"] = pd.Categorical(
                df["kitchen_equipped"], categories=self.KITCHEN_ORDER, ordered=True
            )

        # 5) Booleans -> nullable Int8.
        present_flags = [c for c in self.PRESENCE_FLAGS if c in df.columns]
        df[present_flags] = df[present_flags].fillna(0)
        bool_cols = [c for c in self.BOOL_COLS if c in df.columns]
        df[bool_cols] = df[bool_cols].astype("Int8")

        # 6) Fix swapped coordinates (validated against the postal code).
        df = self._fix_swapped_coordinates(df)

        # 6.5) Repair coord_suspect rows that have a trusted postal-code centroid.
        cent = self._postal_centroids(df)
        mask = df["coord_suspect"] & df["postal_code"].isin(cent.index)
        df.loc[mask, "latitude"] = df.loc[mask, "postal_code"].map(cent["latitude"])
        df.loc[mask, "longitude"] = df.loc[mask, "postal_code"].map(cent["longitude"])

        # 7) Delete specific known-bad listings.
        if "property_url" in df.columns:
            df = df[~df["property_url"].isin(self.URLS_TO_DROP)]

        df = self._flag_suspect_bedroom_count(df)

        # 7.5) Delete physically impossible rows.
        df = self._drop_impossible_rows(df)
        df = df.reset_index(drop=True)

        # 8) Derived feature: price per m².
        df["price_per_m2"] = (df["price"] / df["living_area_m2"]).round(0)

        # 10) Remove internal helper columns from the final df.
        df = df.drop(columns=["coord_suspect", "bedroom_suspect"], errors="ignore")

        self.df = df
        return df


# =========================================================================== #
# 2. GENERAL OVERVIEW VISUALS  (Dan & Irene)
# =========================================================================== #
class DataVisualizer:
    """General overview charts for the cleaned dataset."""

    def __init__(self, df):
        self.df = df

    def dashboard(self):
        """2x3 overview: prices, regions, types, area, EPC, provinces."""
        df = self.df
        fig, axes = plt.subplots(2, 3, figsize=(20, 11))
        fig.suptitle("Real-estate dataset — overview", fontsize=18, fontweight="bold")

        sns.histplot(df["price"].dropna(), bins=60, log_scale=True, ax=axes[0, 0], color="#4C72B0")
        axes[0, 0].set_title("Price distribution (log scale)")
        axes[0, 0].set_xlabel("Price (EUR)")

        sns.boxplot(data=df, x="region", y="price", ax=axes[0, 1], showfliers=False)
        axes[0, 1].set_title("Price by region")
        axes[0, 1].set_ylabel("Price (EUR)")

        df["property_type"].value_counts().plot(
            kind="bar", ax=axes[0, 2], color=["#55A868", "#C44E52"]
        )
        axes[0, 2].set_title("Property type")
        axes[0, 2].set_xlabel("")
        axes[0, 2].tick_params(axis="x", rotation=0)

        sample = df.dropna(subset=["living_area_m2", "price"]).sample(
            min(3000, int(df["price"].notna().sum())), random_state=0
        )
        sns.scatterplot(
            data=sample, x="living_area_m2", y="price", hue="property_type",
            alpha=0.4, s=18, ax=axes[1, 0],
        )
        axes[1, 0].set_title("Living area vs price")
        axes[1, 0].set_xlabel("Living area (m2)")
        axes[1, 0].set_ylabel("Price (EUR)")

        order = [c for c in DataCleaner.EPC_ORDER if c in df["epc_score"].cat.categories]
        sns.countplot(data=df, x="epc_score", order=order, ax=axes[1, 1], color="#8172B3")
        axes[1, 1].set_title("Energy classes (EPC)")
        axes[1, 1].set_xlabel("EPC class")

        df["province"].value_counts().plot(kind="barh", ax=axes[1, 2], color="#CCB974")
        axes[1, 2].set_title("Number of listings per province")
        axes[1, 2].invert_yaxis()

        plt.tight_layout(rect=[0, 0, 1, 0.97])
        save(fig, "overview_dashboard.png")

    def price_map(self):
        """Geographic scatter of price per m2 across Belgium."""
        geo = self.df.dropna(subset=["latitude", "longitude", "price_per_m2"])
        lo, hi = geo["price_per_m2"].quantile([0.01, 0.99])
        geo = geo[(geo["price_per_m2"] >= lo) & (geo["price_per_m2"] <= hi)]

        fig = plt.figure(figsize=(11, 11))
        sc = plt.scatter(
            geo["longitude"], geo["latitude"], c=geo["price_per_m2"],
            cmap="viridis", s=6, alpha=0.6,
        )
        plt.colorbar(sc, label="Price per m2 (EUR)")
        plt.title("Price per m2 map (Belgium)", fontsize=15, fontweight="bold")
        plt.xlabel("Longitude")
        plt.ylabel("Latitude")
        plt.gca().set_aspect("equal", adjustable="datalim")
        save(fig, "price_map_belgium.png")


# =========================================================================== #
# 3. MEETING QUESTIONS Q1 & Q2  (Dan & Irene)
# =========================================================================== #
class MeetingAnswers:

    NON_FEATURES = [
        "price", "price_per_m2",
        "property_url", "address", "city", "postal_code",
        "coord_swapped", "coord_suspect",
        "price_suspect", "area_suspect", "year_suspect",
    ]

    def __init__(self, raw_df, clean_df):
        self.raw = raw_df
        self.df = clean_df

    def which_columns_to_drop(self):
        """Q1 — identify columns to delete and visualise why."""
        raw = self.raw
        reasons = []

        for c in raw.columns:  # constant columns
            if raw[c].nunique(dropna=False) <= 1:
                reasons.append((c, "constant (1 unique value)"))

        seen = {}  # duplicate columns
        for c in raw.columns:
            key = tuple(raw[c].fillna("∅").astype(str))
            if key in seen:
                reasons.append((c, f"duplicate of '{seen[key]}'"))
            else:
                seen[key] = c

        miss = raw.isna().mean()  # mostly-empty columns
        for c in miss[miss > 0.75].index:
            reasons.append((c, f"mostly empty ({miss[c] * 100:.0f}% missing)"))

        report = pd.DataFrame(reasons, columns=["column", "reason"])

        fig, axes = plt.subplots(1, 2, figsize=(18, 9))
        fig.suptitle("Q1 — Which variables to delete, and why", fontsize=16, fontweight="bold")

        miss_sorted = (miss * 100).sort_values(ascending=True)
        colors = ["#C44E52" if v > 75 else "#4C72B0" for v in miss_sorted.values]
        miss_sorted.plot(kind="barh", ax=axes[0], color=colors)
        axes[0].axvline(75, color="#C44E52", linestyle="--", linewidth=1)
        axes[0].set_title("Missing values per column (red dashed = 75%)")
        axes[0].set_xlabel("% missing")

        nun = raw.nunique(dropna=False).sort_values()
        colors2 = ["#C44E52" if v <= 1 else "#55A868" for v in nun.values]
        nun.plot(kind="barh", ax=axes[1], color=colors2, logx=True)
        axes[1].set_title("Unique values per column (log scale; red = constant)")
        axes[1].set_xlabel("# unique values")

        plt.tight_layout(rect=[0, 0, 1, 0.96])
        save(fig, "q1_columns_to_drop.png")
        return report

    def _build_feature_matrix(self, data):
        feats = [c for c in data.columns if c not in self.NON_FEATURES]
        X = pd.DataFrame(index=data.index)
        for c in feats:
            s = data[c]
            if isinstance(s.dtype, pd.CategoricalDtype) or s.dtype == object:
                X[c] = s.astype("category").cat.codes  # NaN -> -1
            else:
                X[c] = pd.to_numeric(s, errors="coerce")
        X = X.fillna(X.median(numeric_only=True))
        return X

    def top_price_drivers(self, n=5):
        """Q2 — rank the variables that most drive the price (RandomForest)."""
        from sklearn.ensemble import RandomForestRegressor

        data = self.df.dropna(subset=["price"]).copy()
        X = self._build_feature_matrix(data)
        y = data["price"]

        model = RandomForestRegressor(n_estimators=300, n_jobs=-1, random_state=0)
        model.fit(X, y)

        importance = pd.Series(model.feature_importances_, index=X.columns).sort_values(
            ascending=False
        )

        fig = plt.figure(figsize=(11, 9))
        colors = ["#C44E52" if i < n else "#9aa0b3" for i in range(len(importance))]
        importance.sort_values().plot(kind="barh", color=colors[::-1])
        plt.title(f"Q2 — Variables driving the price (top {n} in red)", fontsize=15, fontweight="bold")
        plt.xlabel("Importance (RandomForest)")
        plt.tight_layout()
        save(fig, "q2_price_drivers.png")
        return importance.head(n)


# =========================================================================== #
# 4. DATA INTEGRITY — missing values  (Irene)
# =========================================================================== #
def plot_missing_values(df):
    """Bar chart of the proportion of missing values per column."""
    missing_prop = (df.isnull().sum() / len(df)) * 100
    missing_prop = missing_prop[missing_prop > 0].sort_values(ascending=False)
    if missing_prop.empty:
        print("  (no missing values to plot)")
        return

    fig = plt.figure(figsize=(10, 6))
    sns.barplot(x=missing_prop.values, y=missing_prop.index, palette="viridis")
    plt.title("Proportion of Missing Values per Column (%)", fontsize=14, pad=15)
    plt.xlabel("Missing values (%)")
    plt.ylabel("")
    plt.tight_layout()
    save(fig, "missing_values_per_column.png")


# =========================================================================== #
# 5. CORRELATION & MUNICIPALITY PRICES  (Neha)
# =========================================================================== #
class RealEstateAnalyzer:
    EURO_FMT = plt.FuncFormatter(lambda x, p: f"€{x:,.0f}")

    def __init__(self, df):
        self.df = df.copy()
        self.df["price_per_m2"] = self.df["price"] / self.df["living_area_m2"]
        self.flanders = self.df[self.df["region"] == "Flanders"]
        self.wallonia = self.df[self.df["region"] == "Wallonia"]
        self.brussels = self.df[self.df["region"] == "Brussels"]

    def calculate_city_stats(self, region_df):
        stats = region_df.groupby("city").agg(
            avg_price=("price", "mean"),
            median_price=("price", "median"),
            avg_price_per_m2=("price_per_m2", "mean"),
            count=("price", "count"),
        ).reset_index()
        return stats[stats["count"] >= 5]

    def plot_correlation_heatmap(self):
        numeric_columns = [
            "price", "living_area_m2", "bedrooms", "bathrooms",
            "facades", "has_garden", "has_terrace", "is_nearby_city_prestigious",
        ]
        cols = [c for c in numeric_columns if c in self.df.columns]
        df_corr = self.df[cols].dropna(subset=["price"]).astype(float)

        fig = plt.figure(figsize=(8, 6))
        sns.heatmap(
            df_corr.corr()[["price"]], annot=True, fmt=".2f",
            cmap="coolwarm", vmin=-1, vmax=1,
        )
        plt.title("Correlation of the Property Features with Price")
        plt.tight_layout()
        save(fig, "correlation_heatmap.png")

    def plot_municipality_prices(self):
        city_stats = self.calculate_city_stats(self.df)
        fig, axes = plt.subplots(1, 2, figsize=(18, 9))

        city_stats.nlargest(5, "avg_price").plot(
            kind="bar", x="city", y="avg_price", ax=axes[0], color="orange", legend=False
        )
        axes[0].set_title("Top 5 Most Expensive Municipalities", fontweight="bold")
        axes[0].set_xlabel("City", fontweight="bold")
        axes[0].set_ylabel("Average Price (€)", fontweight="bold")
        axes[0].tick_params(axis="x", rotation=45)
        axes[0].yaxis.set_major_formatter(self.EURO_FMT)

        city_stats.nsmallest(5, "avg_price").plot(
            kind="bar", x="city", y="avg_price", ax=axes[1], color="skyblue", legend=False
        )
        axes[1].set_title("Top 5 Least Expensive Municipalities", fontweight="bold")
        axes[1].set_xlabel("City", fontweight="bold")
        axes[1].set_ylabel("Average Price (€)", fontweight="bold")
        axes[1].tick_params(axis="x", rotation=45)
        axes[1].yaxis.set_major_formatter(self.EURO_FMT)

        plt.suptitle("Most vs Least Expensive Municipalities in Belgium", fontsize=16, fontweight="bold")
        fig.subplots_adjust(top=0.88, wspace=0.3)
        save(fig, "municipality_prices.png")

    def _plot_by_region(self, value_col, ylabel, title, fname):
        fig, axes = plt.subplots(3, 2, figsize=(16, 18))
        regions = [
            ("Brussels", self.calculate_city_stats(self.brussels)),
            ("Flanders", self.calculate_city_stats(self.flanders)),
            ("Wallonia", self.calculate_city_stats(self.wallonia)),
        ]
        for i, (region_name, stats) in enumerate(regions):
            stats.nlargest(5, value_col).plot(
                kind="bar", x="city", y=value_col, ax=axes[i][0], color="tomato", legend=False
            )
            axes[i][0].set_title(f"Most Expensive in {region_name}", fontsize=15, fontweight="bold")
            axes[i][0].set_xlabel("City", fontweight="bold")
            axes[i][0].set_ylabel(ylabel, fontweight="bold")
            axes[i][0].tick_params(axis="x", rotation=45)
            axes[i][0].yaxis.set_major_formatter(self.EURO_FMT)

            stats.nsmallest(5, value_col).plot(
                kind="bar", x="city", y=value_col, ax=axes[i][1], color="steelblue", legend=False
            )
            axes[i][1].set_title(f"Least Expensive in {region_name}", fontsize=15, fontweight="bold")
            axes[i][1].set_xlabel("City", fontweight="bold")
            axes[i][1].set_ylabel(ylabel, fontweight="bold")
            axes[i][1].tick_params(axis="x", rotation=45)
            axes[i][1].yaxis.set_major_formatter(self.EURO_FMT)

        plt.suptitle(title, fontsize=16, fontweight="bold")
        plt.tight_layout(rect=[0.02, 0.02, 0.98, 0.96], pad=2.0)
        plt.subplots_adjust(hspace=0.6, wspace=0.3)
        save(fig, fname)

    def plot_by_region_avg(self):
        self._plot_by_region(
            "avg_price", "Average Price (€)",
            "Most vs Least Expensive Municipalities by Region",
            "municipality_prices_by_region.png",
        )

    def plot_by_region_median(self):
        self._plot_by_region(
            "median_price", "Median Price (€)",
            "Most vs Least Expensive Municipalities by Median Price",
            "municipality_median_by_region.png",
        )

    def plot_by_region_per_m2(self):
        self._plot_by_region(
            "avg_price_per_m2", "Avg Price per m² (€)",
            "Most vs Least Expensive Municipalities by Avg Price per m²",
            "municipality_per_m2_by_region.png",
        )


# =========================================================================== #
# 6. PRESTIGE, DISTRIBUTIONS & STRUCTURE  (Victor)
# =========================================================================== #
QUANT_VARS = [
    "price", "living_area_m2", "total_area_m2", "garden_area_m2",
    "bedrooms", "bathrooms", "building_year", "parking_count",
    "facades", "floors_total", "floor_number", "km_from_nearby_city",
]
QUALI_NOMINAL = [
    "property_type", "property_subtype", "state_of_the_building",
    "kitchen_equipped", "epc_score", "region", "province", "city",
    "nearby_city", "postal_code",
]
QUALI_BINARY = [
    "furnished", "has_garage", "has_elevator", "has_garden",
    "has_terrace", "is_nearby_city_prestigious",
]


def _comparable_houses(df):
    """Houses, 2-5 bedrooms, 100-500 m², with the prestige flag mapped to labels."""
    h = df[df["property_type"] == "House"].dropna(
        subset=["is_nearby_city_prestigious", "price", "living_area_m2", "bedrooms"]
    ).copy()
    h = h[h["bedrooms"].isin([2, 3, 4, 5])]
    h = h[h["living_area_m2"].between(100, 500)]
    h["prestigious"] = h["is_nearby_city_prestigious"].map(
        {0: "Non prestigious", 1: "Prestigious", 0.0: "Non prestigious", 1.0: "Prestigious"}
    )
    return h


def plot_prestige_distribution(df):
    """Chart 1 — violin + mean/median bars, prestigious vs non-prestigious."""
    h = _comparable_houses(df)
    n = h["prestigious"].value_counts()
    cap = h["price"].quantile(0.99)

    fig, axes = plt.subplots(1, 2, figsize=(14, 6), gridspec_kw={"width_ratios": [1.3, 1]})

    sns.violinplot(
        data=h, x="prestigious", y="price", ax=axes[0], cut=0, hue="prestigious", legend=False,
        palette={"Non prestigious": "#2E5266", "Prestigious": "#C0775B"},
    )
    sns.stripplot(data=h, x="prestigious", y="price", ax=axes[0], color="black", alpha=0.25, size=3, jitter=0.15)
    axes[0].set_ylim(0, cap)
    axes[0].set_xlabel("")
    axes[0].set_ylabel("Price (€)")
    axes[0].set_xticklabels([f"{lbl}\n(n={n.get(lbl, 0)})" for lbl in ["Non prestigious", "Prestigious"]])
    axes[0].set_title("Price distribution\n(houses, 2-5 bedrooms, 100-500 m²)")

    summary = h.groupby("prestigious")["price"].agg(["mean", "median"]).reindex(
        ["Non prestigious", "Prestigious"]
    )
    summary_plot = summary.reset_index().melt(id_vars="prestigious", var_name="stat", value_name="price")
    sns.barplot(data=summary_plot, x="prestigious", y="price", hue="stat", ax=axes[1], palette=["#888888", "#C0775B"])
    for container in axes[1].containers:
        axes[1].bar_label(container, fmt="%.0f€", fontsize=8, padding=2)
    axes[1].set_xlabel("")
    axes[1].set_ylabel("Price (€)")
    axes[1].set_title("Mean vs median")
    axes[1].legend(title="")

    plt.suptitle(
        "Effect of 'prestigious city' on the price\n(comparable houses, 2-5 bedrooms, 100-500 m²)",
        fontsize=13, y=1.02,
    )
    plt.tight_layout()
    save(fig, "prestige_price_distribution.png")


def plot_prestige_within_5km(df):
    """Chart 2 — boxplot price vs prestige for houses within 5 km of a city."""
    h = _comparable_houses(df)
    t = h[
        h["price"].between(h["price"].quantile(0.01), h["price"].quantile(0.99))
        & (h["km_from_nearby_city"] <= 5)
    ].copy()

    fig, axes = plt.subplots(figsize=(14, 8))
    sns.boxplot(
        data=t, x="is_nearby_city_prestigious", y="price", color="#4C72B0", ax=axes, linewidth=1.5,
        flierprops=dict(marker="o", markersize=4, alpha=0.5),
    )
    axes.set_title(
        "Comparison for comparable houses between price and proximity to a prestigious city (max 5 km)"
    )
    axes.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"€{x / 1000:.0f}k"))
    axes.set_xlabel("Is prestigious city")
    axes.set_ylabel("Price (€)")
    plt.tight_layout()
    save(fig, "prestige_price_within_5km.png")


def plot_price_per_m2_vs_distance(df):
    """Chart 3 — price/m² vs distance, colored by prestige + lowess trend."""
    d = df.copy()
    d["price_m2"] = d["price"] / d["living_area_m2"]
    d = d.replace([np.inf, -np.inf], np.nan).dropna(
        subset=["price_m2", "km_from_nearby_city", "is_nearby_city_prestigious"]
    )
    d = d[d["price_m2"].between(d["price_m2"].quantile(0.01), d["price_m2"].quantile(0.99))]
    d = d[d["km_from_nearby_city"] <= d["km_from_nearby_city"].quantile(0.99)]
    d["prestigious"] = d["is_nearby_city_prestigious"].map(
        {0: "Non prestigious", 1: "Prestigious", 0.0: "Non prestigious", 1.0: "Prestigious"}
    )

    fig, axes = plt.subplots(figsize=(16, 6))
    sns.scatterplot(
        data=d, x="km_from_nearby_city", y="price_m2", hue="prestigious",
        palette={"Non prestigious": "#2E5266", "Prestigious": "#FF2A00"},
        alpha=0.4, s=15, ax=axes, hue_order=["Non prestigious", "Prestigious"],
    )
    try:
        sns.regplot(
            data=d, x="km_from_nearby_city", y="price_m2", scatter=False, lowess=True,
            line_kws={"color": "red", "lw": 2, "label": "Trend (lowess, all properties)"}, ax=axes,
        )
    except RuntimeError:  # statsmodels not installed -> simple linear trend
        sns.regplot(
            data=d, x="km_from_nearby_city", y="price_m2", scatter=False,
            line_kws={"color": "red", "lw": 2, "label": "Trend (linear, all properties)"}, ax=axes,
        )
    axes.set_xlim(0, d["km_from_nearby_city"].quantile(0.97))
    axes.set_xlabel("Distance to nearby city (km)")
    axes.set_ylabel("Price / m² (€)")
    axes.set_title("Price per m² vs distance, coloured by prestigious city")
    axes.legend(title="")
    plt.tight_layout()
    save(fig, "price_per_m2_vs_distance.png")


def plot_spearman_clustermap(df):
    """Chart 4 — Spearman clustermap of the quantitative variables."""
    cols = [c for c in QUANT_VARS if c in df.columns]
    corr_spearman = df[cols].corr(method="spearman")

    g = sns.clustermap(
        corr_spearman.fillna(0), annot=corr_spearman.round(2), fmt="",
        cmap="RdBu_r", center=0, vmin=-1, vmax=1, figsize=(12, 12),
        method="average", metric="euclidean", linewidths=0.5, linecolor="white",
        annot_kws={"size": 9}, cbar_pos=(1.02, 0.3, 0.03, 0.4), dendrogram_ratio=(0.12, 0.12),
    )
    g.ax_heatmap.set_xticklabels(g.ax_heatmap.get_xmajorticklabels(), rotation=45, ha="right", fontsize=9)
    g.ax_heatmap.set_yticklabels(g.ax_heatmap.get_ymajorticklabels(), rotation=0, fontsize=9)
    g.fig.suptitle(
        "Spearman correlation between quantitative variables\n"
        "(hierarchical clustering reveals correlated groups)",
        fontsize=13, y=1.02,
    )
    save(g.fig, "spearman_clustermap.png")


def plot_living_area_histogram(df):
    """Chart 5 — histogram of living area (capped at p99)."""
    fig, axes = plt.subplots(figsize=(16, 10))
    sns.histplot(df["living_area_m2"].dropna(), ax=axes, color="#FFA200")
    axes.set_title("Number of properties per living area (m²)")
    axes.set_xlabel("Living area (m²)")
    axes.set_ylabel("Number of properties")
    axes.set_xlim(0, df["living_area_m2"].quantile(0.99))
    plt.tight_layout()
    save(fig, "living_area_histogram.png")


def plot_qualitative_grid(df):
    """Chart 6 — grid of bar charts for qualitative variables (top 8 each)."""
    quali_vars = [c for c in (QUALI_NOMINAL + QUALI_BINARY) if c in df.columns][:12]
    fig, axes = plt.subplots(3, 4, figsize=(20, 12))
    for ax, col in zip(axes.flat, quali_vars):
        vc = df[col].value_counts(dropna=True).head(8)
        sns.barplot(x=vc.values, y=vc.index.astype(str), ax=ax, color="#C0775B")
        ax.set_title(col, fontsize=10)
    for ax in axes.flat[len(quali_vars):]:
        ax.axis("off")
    plt.tight_layout()
    save(fig, "qualitative_variables_grid.png")


def plot_quantitative_grid(df):
    """Chart 7 — grid of histograms for quantitative variables (p1-p95)."""
    quant_vars = [c for c in QUANT_VARS if c in df.columns][:12]
    fig, axes = plt.subplots(3, 4, figsize=(20, 12))
    for ax, col in zip(axes.flat, quant_vars):
        data = df[col].dropna()
        if len(data) == 0:
            ax.axis("off")
            continue
        data = data[data.between(data.quantile(0.01), data.quantile(0.95))]
        sns.histplot(data, bins=40, kde=True, ax=ax, color="#2E5266")
        ax.set_title(f"{col}  (n={len(data)}, missing={df[col].isna().mean() * 100:.0f}%)", fontsize=10)
    for ax in axes.flat[len(quant_vars):]:
        ax.axis("off")
    plt.tight_layout()
    save(fig, "quantitative_variables_grid.png")


def plot_price_per_m2_by_province_surface(df):
    """Chart 8 (static version of the animated plotly) — price/m² by province
    across living-area brackets, as small-multiple lines."""
    d = df.copy()
    d["price_m2"] = d["price"] / d["living_area_m2"]
    d = d.replace([np.inf, -np.inf], np.nan).dropna(subset=["price_m2", "living_area_m2", "province"])
    d = d[d["price_m2"].between(d["price_m2"].quantile(0.01), d["price_m2"].quantile(0.99))]

    bins = [0, 50, 100, 150, 200, 300, 500, np.inf]
    labels = ["0-50", "50-100", "100-150", "150-200", "200-300", "300-500", "500+"]
    d["surface_bin"] = pd.cut(d["living_area_m2"], bins=bins, labels=labels, include_lowest=True)

    agg = (
        d.groupby(["surface_bin", "province"], observed=True)["price_m2"]
        .mean()
        .reset_index()
    )

    fig, ax = plt.subplots(figsize=(14, 8))
    for province, sub in agg.groupby("province"):
        sub = sub.set_index("surface_bin").reindex(labels)
        ax.plot(labels, sub["price_m2"].values, marker="o", label=province)
    ax.set_title("Average price / m² by province, across living-area brackets", fontsize=14, fontweight="bold")
    ax.set_xlabel("Living area bracket (m²)")
    ax.set_ylabel("Average price / m² (€)")
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, p: f"€{x:,.0f}"))
    ax.legend(title="Province", bbox_to_anchor=(1.02, 1), loc="upper left")
    plt.tight_layout()
    save(fig, "price_per_m2_by_province_surface.png")


# =========================================================================== #
# MAIN
# =========================================================================== #
def main():
    print("Immo Eliza — analysis pipeline")
    print("=" * 50)

    if not RAW_CSV.exists():
        raise FileNotFoundError(
            f"Raw dataset not found at {RAW_CSV}.\n"
            "Place the scraped CSV there (or edit RAW_CSV at the top of this file)."
        )

    # --- 1. Clean -------------------------------------------------------------
    print("\n[1/3] Cleaning data ...")
    cleaner = DataCleaner(RAW_CSV)
    df = cleaner.clean()
    CLEANED_CSV.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(CLEANED_CSV, index=False)
    print(f"  cleaned dataset: {df.shape[0]} rows x {df.shape[1]} columns")
    print(f"  saved  {CLEANED_CSV.relative_to(BASE_DIR)}")

    # --- 2. Overview + meeting answers (Dan & Irene) --------------------------
    print("\n[2/3] Generating visuals ...")
    viz = DataVisualizer(df)
    viz.dashboard()
    viz.price_map()

    qa = MeetingAnswers(cleaner.raw, df)
    qa.which_columns_to_drop()
    qa.top_price_drivers(n=5)

    # Data integrity (Irene)
    plot_missing_values(df)

    # Correlation & municipalities (Neha)
    analyzer = RealEstateAnalyzer(df)
    analyzer.plot_correlation_heatmap()
    analyzer.plot_municipality_prices()
    analyzer.plot_by_region_avg()
    analyzer.plot_by_region_median()
    analyzer.plot_by_region_per_m2()

    # Prestige / distributions / structure (Victor)
    plot_prestige_distribution(df)
    plot_prestige_within_5km(df)
    plot_price_per_m2_vs_distance(df)
    plot_spearman_clustermap(df)
    plot_living_area_histogram(df)
    plot_qualitative_grid(df)
    plot_quantitative_grid(df)
    plot_price_per_m2_by_province_surface(df)

    # --- 3. Done --------------------------------------------------------------
    n_imgs = len(list(IMAGES_DIR.glob("*.png")))
    print("\n[3/3] Done.")
    print(f"  {n_imgs} images saved to {IMAGES_DIR.relative_to(BASE_DIR)}/")


if __name__ == "__main__":
    main()
