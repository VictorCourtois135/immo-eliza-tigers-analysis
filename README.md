# 🏠 Immo Eliza — Belgian Real-Estate Analysis

> Preliminary analysis of the Belgian residential property market, built to help
> **Immo Eliza** estimate property value faster and more accurately than its competitors.

This repository turns a raw scraped dataset of Belgian property listings into a
clean, analysable dataset and a set of insight-driven visualisations answering two
management questions:

1. **What are the most interesting insights about the Belgian real-estate market?**
2. **Which variables matter most when determining the price of a property?**

---

## 📑 Table of contents

- [Our client](#-our-client)
- [Key insights](#-key-insights-tldr)
- [Repository structure](#-repository-structure)
- [Getting started](#-getting-started)
- [How to run](#-how-to-run)
- [The dataset](#-the-dataset)
- [Visuals](#-visuals)
- [Team & roles](#-team--roles)
- [Tech stack](#-tech-stack)

---

## 🎯 Our client

We framed the whole analysis around a single persona:

> **"Marc, the value investor."**
> Marc looks for properties with the best return potential across Belgium. He needs
> to know **where** prices are high or low, **what** drives a property's value, and
> **which features** are worth paying for. He is not technical — he wants clear charts
> and concrete recommendations, not statistics.

Every chart and recommendation in this project is meant to answer one of Marc's
questions: *Where should I buy? What should I look at? What is actually worth it?*

---

## 💡 Key insights (TL;DR)

- **Size is king.** Living area is by far the strongest price driver — bigger
  properties cost more, ahead of bedrooms, bathrooms and total surface.
- **Location is the second lever.** A clear north/south gradient (latitude) and the
  proximity to a prestigious city strongly shape price. Comparable houses near a
  prestigious city cost on average **~2× more** (≈ €843k vs €419k).
- **Energy rating matters.** EPC score ranks among the top price drivers — an A
  property sells better than a G.
- **Price per m² falls as size grows.** Small properties cost more per m² than large
  ones; price/m² also decreases with distance from the nearest city.
- **Brussels is the priciest market per m²**, stable across communes; **Wallonia** is
  cheapest overall, with rural villages offering potential value buys (but thinner demand).
- **Cosmetic features** (garden, terrace) add value but are *not* primary drivers.

> **Bottom line for Marc:** *Where you buy matters more than what you buy.* Focus on
> living area and location; treat gardens and terraces as bonuses, not decision factors.

---

## 📁 Repository structure

```
immo-eliza-<team>-analysis/
│
├── data/
│   ├── raw/
│   │   └── properties_parsed.csv        # original scraped dataset (untouched)
│   └── cleaned/
│       └── properties_final.csv         # cleaned dataset (output of main.py)
│
├── analysis/                            # exploratory notebooks (one per analyst)
│   ├── notebook_data_cleaning_irene.ipynb
│   ├── irene_dataset_check.ipynb
│   ├── irene_changes_on_dan_nb.ipynb    # cleaning pipeline + Q1/Q2 answers
│   ├── irene-visuals-nb.ipynb
│   ├── analysis_neha.ipynb              # correlation + municipality prices
│   └── Victor_notebook.ipynb            # prestige, distributions, structure
│
├── images/                             # all generated visuals (.png)
│
├── reports/
│   └── presentation.pdf                # final non-technical presentation
│
├── main.py                            # cleans data + generates every visual
├── DATA_DICTIONARY.md                 # description of every column
├── requirements.txt
└── README.md
```

---

## 🚀 Getting started

### Prerequisites
- Python 3.10+
- `pip`

### Installation

```bash
# 1. Clone the repository
git clone https://github.com/<your-org>/immo-eliza-<team>-analysis.git
cd immo-eliza-<team>-analysis

# 2. (Recommended) create a virtual environment
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt
```

**`requirements.txt`**

```
pandas
numpy
matplotlib
seaborn
scikit-learn
statsmodels
```

---

## ▶️ How to run

Place the raw dataset at `data/raw/properties_parsed.csv`, then from the repo root:

```bash
python main.py
```

This will:

1. **Clean** the raw data and save it to `data/cleaned/properties_final.csv`
2. **Generate all 18 visuals** and save them to `images/`

The script is reproducible and head-less (no display needed): the CEO can re-run it
after any change to regenerate every figure.

> Want to explore step by step? Open the notebooks in `analysis/`.

---

## 📊 The dataset

- **~12,600 property listings** across Belgium (Flanders, Wallonia, Brussels)
- **~34 columns** covering price, surface, rooms, location, energy and amenities
- Cleaned **non-destructively**: only physically impossible rows are removed; ambiguous
  values are flagged, not deleted.

👉 Full description of every column in **[DATA_DICTIONARY.md](DATA_DICTIONARY.md)**.

### Cleaning summary
- Dropped the constant column `price_type` and the duplicate `property_id`.
- Standardised city names, energy (EPC), building state and kitchen as ordered categories.
- Repaired swapped GPS coordinates, validated against the postal code.
- Removed only physically impossible rows (price < €19,900, living area < 10 m², etc.).
- Derived `price_per_m2` for per-surface comparisons.

---

## 🖼️ Visuals

All figures are produced by `main.py` into `images/`:

| File | What it shows |
| --- | --- |
| `overview_dashboard.png` | Prices, regions, types, area, EPC, provinces at a glance |
| `price_map_belgium.png` | Geographic map of price per m² |
| `q1_columns_to_drop.png` | Which variables to delete and why |
| `q2_price_drivers.png` | Top price drivers (RandomForest importance) |
| `missing_values_per_column.png` | Proportion of missing values per column |
| `correlation_heatmap.png` | Correlation of features with price |
| `municipality_prices.png` | Most vs least expensive municipalities (Belgium) |
| `municipality_prices_by_region.png` | Same, by region (average) |
| `municipality_median_by_region.png` | Same, by region (median) |
| `municipality_per_m2_by_region.png` | Same, by region (price / m²) |
| `prestige_price_distribution.png` | Price: prestigious vs non-prestigious city |
| `prestige_price_within_5km.png` | Prestige effect within 5 km of a city |
| `price_per_m2_vs_distance.png` | Price / m² vs distance, coloured by prestige |
| `spearman_clustermap.png` | Correlation clusters between numeric variables |
| `living_area_histogram.png` | Distribution of properties by living area |
| `qualitative_variables_grid.png` | Frequency of each categorical variable |
| `quantitative_variables_grid.png` | Distribution of each numeric variable |
| `price_per_m2_by_province_surface.png` | Price / m² by province across size brackets |

---

## 👥 Team & roles

| Member | Role |
| --- | --- |
| Neha | Project Lead (Agile Master) |
| Victor  | Git Commander (Repo Manager) |
| Dan | Documentation Specialist |
| Irene | QA & Data Architect |

> Contributors to the analysis: Irene, Neha, Victor, Dan.
> _Fill in the role table above with your team members._

---

## 🛠️ Tech stack

- **pandas** / **numpy** — data wrangling
- **matplotlib** / **seaborn** — visualisation
- **scikit-learn** — feature-importance ranking (RandomForest)
- **statsmodels** — trend smoothing (lowess)
- **Jupyter** — exploratory analysis

---

*Built as part of the BeCode Data Science training — Immo Eliza analysis project.*
