---
title: Wages
---

# Wages, by country

The same cleaning and the same moments, run once per country. One
formula, one method, many batches.

### raw-wages

Payroll extract for one country, 2019–2020. One row per worker-year,
wages in nominal local currency. Each country's extract has its own
known coding errors — non-positive wages appear in both, and the
cleaning step drops them on purpose so the drop stays visible.

- props: country
- produces: data/raw/{country}/wages.csv

### clean-wages

Drop non-positive wages. One row per worker-year, no duplicates. The
row count must fall — if nothing is dropped, the extract changed.

Applies to any country whose extract carries the standard columns.

- props: country
- consumes: raw-wages
- produces: wages-panel

### wage-moments

Mean and variance of **log** wages for one country, on its clean panel.
Variance is the population form, not the sample form.

- props: country
- consumes: wages-panel
- produces: country-moments

### wage-comparison

Every country's moments in one table, alphabetical by country, four
decimal places. This is the deliverable — it is *not* templated,
because there is one of it.

- consumes: country-moments
- produces: comparison-table
