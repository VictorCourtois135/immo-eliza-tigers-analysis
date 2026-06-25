# 📖 Data Dictionary — `properties_final.csv`

This document describes every column of the cleaned dataset
(`data/cleaned/properties_final.csv`), produced by `main.py` from the raw scraped file
(`data/raw/properties_parsed.csv`).

**Legend**
- **Type** — `float`, `Int64`/`Int8` (nullable integer), `category` (ordered/nominal), `string`, `bool`
- **Unit** — the measurement unit, where applicable
- **Missing** — rough share of missing values observed in the raw data (indicative)
- A *derived* column is computed during cleaning; a *flag* is added during cleaning.

---

## 1. Identifiers & location

| Column | Type | Unit | Description | Notes |
| --- | --- | --- | --- | --- |
| `property_url` | string | — | Unique URL of the listing | Acts as the row identifier (kept; the duplicate `property_id` is dropped). |
| `address` | string | — | Street address of the property | High cardinality; not used as a model feature. |
| `city` | string | — | Municipality name | Cleaned: slugs like `la-roche-en-ardenne` → `La Roche En Ardenne`. |
| `postal_code` | Int64 | — | Belgian postal code | Also used to validate/repair GPS coordinates. |
| `region` | category | — | Region: `Flanders`, `Wallonia`, `Brussels` | Nominal. |
| `province` | category | — | Belgian province (e.g. `Antwerp`, `Hainaut`) | Nominal; Brussels = single region/province. |
| `latitude` | float | degrees | GPS latitude | Swapped coordinates repaired against the postal-code centroid. |
| `longitude` | float | degrees | GPS longitude | See `latitude`. |
| `nearby_city` | category | — | Nearest reference city | Nominal. |
| `km_from_nearby_city` | float | km | Distance to the nearest reference city | Used in distance/price analyses. |
| `is_nearby_city_prestigious` | Int8 (bool) | 0/1 | Whether the nearby city is "prestigious" | Strong price signal in the analysis. |

---

## 2. Price

| Column | Type | Unit | Description | Notes |
| --- | --- | --- | --- | --- |
| `price` | float | € | Listed sale price | **Target variable.** Rows with price < €19,900 removed as impossible. |
| `price_per_m2` | float | €/m² | *Derived:* `price / living_area_m2` | Added during cleaning; used for per-surface comparisons. |

---

## 3. Surface

| Column | Type | Unit | Description | Notes |
| --- | --- | --- | --- | --- |
| `living_area_m2` | float | m² | Habitable living area | **Strongest price driver.** Rows < 10 m² removed as impossible. |
| `total_area_m2` | float | m² | Total surface (land + building) | Correlated with living area and price. |
| `garden_area_m2` | float | m² | Garden surface | **~78% missing** — weak/unreliable; candidate for deletion. |

---

## 4. Rooms & layout

| Column | Type | Unit | Description | Notes |
| --- | --- | --- | --- | --- |
| `bedrooms` | Int64 | count | Number of bedrooms | Proxy for usable size; correlated with price. |
| `bathrooms` | Int64 | count | Number of bathrooms | Correlated with price. |
| `facades` | Int64 | count | Number of façades (2–4) | More façades ≈ more detached ≈ pricier (moderate). |
| `floors_total` | Int64 | count | Total number of floors in the building | — |
| `floor_number` | Int64 | floor | Floor on which the unit sits | **~71% missing** (mostly N/A for houses). |
| `parking_count` | Int64 | count | Number of parking spaces | — |

---

## 5. Building characteristics

| Column | Type | Unit | Description | Notes |
| --- | --- | --- | --- | --- |
| `building_year` | Int64 | year | Year of construction | Rows with year > 2026 removed as impossible. |
| `state_of_the_building` | category (ordered) | — | Condition of the building | Order: `New > Excellent > Fully renovated > Normal > To renovate > To restore > Under construction > To demolish`. Synonym `To be renovated` → `To renovate`. |
| `epc_score` | category (ordered) | — | Energy performance class | Order: `A++ > A+ > A > B+ > B > C > D > E+ > E > F > G`. Among top price drivers. |
| `kitchen_equipped` | category (ordered) | — | Kitchen equipment level | Order: `Not equipped < Partially equipped < Fully equipped < Super equipped`. **~74% missing.** |
| `property_type` | category | — | `House` or `Apartment` | Nominal. |
| `property_subtype` | category | — | Detailed type (villa, studio, …) | Nominal, higher cardinality. |

---

## 6. Amenities (binary flags)

All stored as nullable `Int8` with values `1` = present, `0` = not mentioned.
For the presence flags, a missing value is interpreted as "not present" (`0`) — a
**modelling choice**, since the scraper only recorded "Yes".

| Column | Type | Description |
| --- | --- | --- |
| `furnished` | Int8 (bool) | Property is sold furnished |
| `has_garage` | Int8 (bool) | Has a garage |
| `has_garden` | Int8 (bool) | Has a garden |
| `has_terrace` | Int8 (bool) | Has a terrace |
| `has_elevator` | Int8 (bool) | Building has an elevator |

---

## 7. Cleaning flags (added during processing)

| Column | Type | Description |
| --- | --- | --- |
| `coord_swapped` | bool | `True` if latitude/longitude were swapped back into the correct order (validated against the postal-code centroid). |

> Internal review flags `coord_suspect` and `bedroom_suspect` are created during
> cleaning but **dropped** from the final dataset (not useful for analysis).

---

## 8. Columns removed during cleaning

| Column | Reason for removal |
| --- | --- |
| `price_type` | **Constant** — a single value (`sell`) → zero information. |
| `property_id` | **Duplicate** — identical to `property_url`; one is enough. |

> Borderline candidates kept but flagged as weak signal: `garden_area_m2` (78% missing),
> `kitchen_equipped` (74%), `floor_number` (71%).

---

## Cleaning rules at a glance

**Rows are deleted only when physically impossible:**
- `price` < €19,900
- `living_area_m2` < 10 m²
- `living_area_m2` < 5 m² per bedroom
- `building_year` > 2026

**Everything else is corrected conservatively or flagged**, never silently altered —
so the dataset stays trustworthy and reproducible.
