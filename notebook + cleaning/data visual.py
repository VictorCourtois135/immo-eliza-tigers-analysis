"""
real_estate_analysis.py
=======================

Object-oriented analysis pipeline for the Belgian real-estate dataset.

Three responsibilities, three classes:
1. ``DataCleaner``     — loads the raw CSV and returns a cleaned DataFrame.
2. ``DataVisualizer``  — general overview charts (dashboard + price map).
3. ``MeetingAnswers``  — answers the two meeting questions, each with a chart:
                         (Q1) which variables to delete and why,
                         (Q2) the five variables that most drive the price.

Usage:
    python real_estate_analysis.py path/to/properties_cleaned.csv
"""

import sys
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
from sklearn.ensemble import RandomForestRegressor

sns.set_theme(style="whitegrid")


# ── Data cleaning ─────────────────────────────────────────────────────────────

class DataCleaner:
    """Loads the raw scraper CSV and produces a cleaned DataFrame.

    All cleaning knowledge (category orders, synonyms, geographic bounds) lives
    here as class attributes, so there is a single place to update.
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

    def __init__(self, path: str):
        """Store the path and load the raw CSV (kept in ``self.raw``)."""
        self.path = path
        self.raw = pd.read_csv(path)   # untouched copy, useful for the Q1 audit
        self.df = None                 # filled by clean()

    # ----- geographic helpers -----

    @staticmethod
    def _haversine(lat1, lon1, lat2, lon2):
        """Great-circle distance in km between two points (decimal degrees)."""
        R = 6371
        lat1, lon1, lat2, lon2 = map(np.radians, [lat1, lon1, lat2, lon2])
        a = np.sin((lat2 - lat1) / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin((lon2 - lon1) / 2) ** 2
        return 2 * R * np.arcsin(np.sqrt(a))

    def _postal_centroids(self, df):
        """Median lat/lon per postal code, from rows already inside Belgium.

        Independent ground truth (postal code comes from the URL) used to
        validate coordinate swaps.
        """
        valid = df["latitude"].between(*self.BE_LAT) & df["longitude"].between(*self.BE_LON)
        return df[valid].groupby("postal_code")[["latitude", "longitude"]].median()

    def _fix_swapped_coordinates(self, df):
        """Swap lat/lon only when it brings the point near its postal centroid.

        Rows where the swap is not confirmed are left untouched and flagged
        ``coord_suspect``. Adds ``coord_swapped`` and ``coord_suspect``.
        """
        cent = self._postal_centroids(df)
        candidate = ~(df["latitude"].between(*self.BE_LAT) & df["longitude"].between(*self.BE_LON))

        df["coord_swapped"] = False
        df["coord_suspect"] = False

        for i in df.index[candidate]:
            pc = df.at[i, "postal_code"]
            lat, lon = df.at[i, "latitude"], df.at[i, "longitude"]
            if pd.isna(lat) or pc not in cent.index:
                df.at[i, "coord_suspect"] = True
                continue
            clat, clon = cent.loc[pc, "latitude"], cent.loc[pc, "longitude"]
            if self._haversine(lon, lat, clat, clon) < self.SWAP_MAX_KM:
                df.at[i, "latitude"], df.at[i, "longitude"] = lon, lat
                df.at[i, "coord_swapped"] = True
            else:
                df.at[i, "coord_suspect"] = True
        return df

    # ----- main entry -----

    def clean(self) -> pd.DataFrame:
        """Run the full cleaning pipeline and return the cleaned DataFrame."""
        df = self.raw.copy()

        # 1) Drop useless columns (constant + duplicate). See MeetingAnswers Q1.
        df = df.drop(columns=[c for c in ["price_type", "property_id"] if c in df.columns])

        # 2) Normalise the city slug: "la-roche-en-ardenne" -> "La Roche En Ardenne".
        df["city"] = df["city"].str.replace("-", " ", regex=False).str.title()

        # 3) Building state: merge synonyms + ordered category.
        df["state_of_the_building"] = df["state_of_the_building"].replace(self.STATE_SYNONYMS)
        df["state_of_the_building"] = pd.Categorical(
            df["state_of_the_building"], categories=self.STATE_ORDER, ordered=True
        )

        # 4) EPC and kitchen as ordered categories (values outside the list -> NaN).
        df["epc_score"] = pd.Categorical(df["epc_score"], categories=self.EPC_ORDER, ordered=True)
        df["kitchen_equipped"] = pd.Categorical(
            df["kitchen_equipped"], categories=self.KITCHEN_ORDER, ordered=True
        )

        # 5) Booleans -> nullable Int8. NOTE: has_* only recorded "Yes" (1), so a
        #    NaN means "not mentioned"; NaN->0 is a modelling CHOICE.
        for col in self.BOOL_COLS:
            if col in self.PRESENCE_FLAGS:
                df[col] = df[col].fillna(0)
            df[col] = df[col].astype("Int8")

        # 6) Fix swapped coordinates (validated against the postal code).
        df = self._fix_swapped_coordinates(df)

        # 7) Flag (without modifying) suspect values for later investigation.
        df["price_suspect"] = (df["price"] < 20_000) | (df["price"] > 10_000_000)
        df["area_suspect"]  = (df["living_area_m2"] < 10) | (df["living_area_m2"] > 2000)
        df["year_suspect"]  = (df["building_year"] < 1700) | (df["building_year"] > 2030)

        # 8) Derived feature: price per m².
        df["price_per_m2"] = (df["price"] / df["living_area_m2"]).round(0)

        self.df = df
        return df


# ── General visualization ─────────────────────────────────────────────────────

class DataVisualizer:
    """General overview charts for the cleaned dataset."""

    def __init__(self, df: pd.DataFrame):
        self.df = df

    def dashboard(self, out_prefix: str = "viz") -> str:
        """2x3 overview dashboard (prices, types, area, EPC, provinces)."""
        df = self.df
        fig, axes = plt.subplots(2, 3, figsize=(20, 11))
        fig.suptitle("Real-estate dataset — overview", fontsize=18, fontweight="bold")

        sns.histplot(df["price"].dropna(), bins=60, log_scale=True, ax=axes[0, 0], color="#4C72B0")
        axes[0, 0].set_title("Price distribution (log scale)")
        axes[0, 0].set_xlabel("Price (€)")

        sns.boxplot(data=df, x="region", y="price", ax=axes[0, 1], showfliers=False)
        axes[0, 1].set_title("Price by region")
        axes[0, 1].set_ylabel("Price (€)")

        df["property_type"].value_counts().plot(kind="bar", ax=axes[0, 2], color=["#55A868", "#C44E52"])
        axes[0, 2].set_title("Property type")
        axes[0, 2].set_xlabel("")
        axes[0, 2].tick_params(axis="x", rotation=0)

        sample = df.dropna(subset=["living_area_m2", "price"]).sample(
            min(3000, df["price"].notna().sum()), random_state=0
        )
        sns.scatterplot(data=sample, x="living_area_m2", y="price", hue="property_type",
                        alpha=0.4, s=18, ax=axes[1, 0])
        axes[1, 0].set_title("Living area vs price")
        axes[1, 0].set_xlabel("Living area (m²)")
        axes[1, 0].set_ylabel("Price (€)")

        order = [c for c in DataCleaner.EPC_ORDER if c in df["epc_score"].cat.categories]
        sns.countplot(data=df, x="epc_score", order=order, ax=axes[1, 1], color="#8172B3")
        axes[1, 1].set_title("Energy classes (EPC)")
        axes[1, 1].set_xlabel("EPC class")

        df["province"].value_counts().plot(kind="barh", ax=axes[1, 2], color="#CCB974")
        axes[1, 2].set_title("Number of listings per province")
        axes[1, 2].invert_yaxis()

        plt.tight_layout(rect=[0, 0, 1, 0.97])
        path = f"{out_prefix}_dashboard.png"
        plt.savefig(path, dpi=120, bbox_inches="tight")
        plt.close()
        return path

    def price_map(self, out_prefix: str = "viz") -> str:
        """Geographic scatter of price per m² across Belgium."""
        geo = self.df.dropna(subset=["latitude", "longitude", "price_per_m2"])
        lo, hi = geo["price_per_m2"].quantile([0.01, 0.99])   # clip for colour scale
        geo = geo[(geo["price_per_m2"] >= lo) & (geo["price_per_m2"] <= hi)]

        plt.figure(figsize=(11, 11))
        sc = plt.scatter(geo["longitude"], geo["latitude"], c=geo["price_per_m2"],
                         cmap="viridis", s=6, alpha=0.6)
        plt.colorbar(sc, label="Price per m² (€)")
        plt.title("Price per m² map (Belgium)", fontsize=15, fontweight="bold")
        plt.xlabel("Longitude")
        plt.ylabel("Latitude")
        plt.gca().set_aspect("equal", adjustable="datalim")
        path = f"{out_prefix}_map.png"
        plt.savefig(path, dpi=120, bbox_inches="tight")
        plt.close()
        return path


# ── Meeting questions ─────────────────────────────────────────────────────────

class MeetingAnswers:
    """Answers the two meeting questions, each backed by a chart.

    Q1 works on the RAW data (to justify the deletions on the original columns);
    Q2 works on the CLEANED data (to rank what drives the price).
    """

    # Columns excluded from the price model: target itself, leakage, identifiers,
    # free text, and the diagnostic flags added during cleaning.
    NON_FEATURES = [
        "price", "price_per_m2",               # target + leakage (price_per_m2 = price/area)
        "property_url", "address", "city", "postal_code",  # identifiers / high-cardinality
        "coord_swapped", "coord_suspect",
        "price_suspect", "area_suspect", "year_suspect",
    ]

    def __init__(self, raw_df: pd.DataFrame, clean_df: pd.DataFrame):
        self.raw = raw_df
        self.df = clean_df

    # ----- Q1: which variables to delete -----

    def which_columns_to_drop(self, out: str = "q1_columns_to_drop.png") -> pd.DataFrame:
        """Q1 — identify columns to delete and visualise why.

        Three deletion reasons are detected on the RAW data:
        - constant      : a single unique value (no information),
        - duplicate     : identical to another column (redundant),
        - mostly empty  : very high share of missing values (weak signal).

        Produces a 2-panel chart (missing share + unique counts) and returns a
        table of (column, reason).
        """
        raw = self.raw
        reasons = []

        # Constant columns (1 unique value -> zero information).
        for c in raw.columns:
            if raw[c].nunique(dropna=False) <= 1:
                reasons.append((c, "constant (1 unique value)"))

        # Duplicate columns (identical content to an earlier column).
        seen = {}
        for c in raw.columns:
            key = tuple(raw[c].fillna("∅").astype(str))
            if key in seen:
                reasons.append((c, f"duplicate of '{seen[key]}'"))
            else:
                seen[key] = c

        # Mostly-empty columns (candidates, judgment call) above 75% missing.
        miss = raw.isna().mean()
        for c in miss[miss > 0.75].index:
            reasons.append((c, f"mostly empty ({miss[c]*100:.0f}% missing)"))

        report = pd.DataFrame(reasons, columns=["column", "reason"])

        # --- chart: missingness (left) + unique counts (right) ---
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
        plt.savefig(out, dpi=120, bbox_inches="tight")
        plt.close()
        return report

    # ----- Q2: top price drivers -----

    def _build_feature_matrix(self, data: pd.DataFrame):
        """Encode features for a tree model: numeric as-is, categoricals as codes.

        NOTE: nominal categories (region, nearby_city, ...) are label-encoded for
        simplicity, which keeps ONE importance value per variable — convenient
        for answering "which variables matter". A tree model handles this fine
        for ranking purposes (it splits on code values).
        """
        feats = [c for c in data.columns if c not in self.NON_FEATURES]
        X = pd.DataFrame(index=data.index)
        for c in feats:
            s = data[c]
            if isinstance(s.dtype, pd.CategoricalDtype) or s.dtype == object:
                X[c] = s.astype("category").cat.codes          # NaN -> -1
            else:
                X[c] = pd.to_numeric(s, errors="coerce")
        # Fill remaining numeric gaps with the column median.
        X = X.fillna(X.median(numeric_only=True))
        return X

    def top_price_drivers(self, n: int = 5, out: str = "q2_feature_importance.png") -> pd.Series:
        """Q2 — rank the variables that most drive the price.

        Trains a RandomForest to predict ``price`` and reads its feature
        importances. Suspect price/area rows are excluded so the model learns on
        clean signal. Produces an importance bar chart and returns the top-n.

        Returns:
            A pandas Series (variable -> importance), sorted descending, top n.
        """
        df = self.df
        # Train on rows with a valid price and no flagged price/area anomaly.
        data = df[~df["price_suspect"] & ~df["area_suspect"]].dropna(subset=["price"])
        X = self._build_feature_matrix(data)
        y = data["price"]

        model = RandomForestRegressor(
            n_estimators=300, max_depth=None, n_jobs=-1, random_state=0
        )
        model.fit(X, y)

        importance = pd.Series(model.feature_importances_, index=X.columns).sort_values(ascending=False)
        top = importance.head(n)

        # --- chart: full ranking with the top-n highlighted ---
        plt.figure(figsize=(11, 9))
        colors = ["#C44E52" if i < n else "#9aa0b3" for i in range(len(importance))]
        importance.sort_values().plot(kind="barh", color=colors[::-1])
        plt.title(f"Q2 — Variables driving the price (top {n} in red)",
                  fontsize=15, fontweight="bold")
        plt.xlabel("Importance (RandomForest)")
        plt.tight_layout()
        plt.savefig(out, dpi=120, bbox_inches="tight")
        plt.close()
        return top


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    csv_path = sys.argv[1] if len(sys.argv) > 1 else "properties_cleaned.csv"

    # 1) Clean.
    cleaner = DataCleaner(csv_path)
    df = cleaner.clean()
    print(f"Cleaned: {df.shape[0]} rows × {df.shape[1]} columns")

    # 2) General visualisations.
    viz = DataVisualizer(df)
    viz.dashboard()
    viz.price_map()
    print("General charts: viz_dashboard.png, viz_map.png")

    # 3) Meeting questions.
    qa = MeetingAnswers(cleaner.raw, df)

    q1 = qa.which_columns_to_drop()
    print("\nQ1 — columns to delete:")
    print(q1.to_string(index=False))

    q2 = qa.top_price_drivers(n=5)
    print("\nQ2 — top 5 price drivers:")
    print(q2.round(3).to_string())

    df.to_csv("properties_final.csv", index=False)
    print("\nSaved: properties_final.csv, q1_columns_to_drop.png, q2_feature_importance.png")