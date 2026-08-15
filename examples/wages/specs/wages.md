---
title: Wages
---

# Wages

A four-worker panel, cleaned, summarised, and rendered as a table.
Opening prose is narrative: context for the reader, signed by no one.

### raw-wages

Payroll extract, four workers, 2019–2020. One row per worker-year,
wages in nominal euros. A negative wage in 2020 is a known coding error
in the source system — do not "fix" it upstream, the cleaning step drops
it on purpose so the drop stays visible.

- produces: data/raw/wages.csv

### clean-wages

Drop non-positive wages. One row per worker-year, no duplicates. The
row count must fall — if nothing is dropped, the extract changed.

- consumes: raw-wages
- produces: wages-panel

### wage-moments

Mean and variance of **log** wages, by year, on the clean panel.
Variance is the population form, not the sample form.

- consumes: wages-panel
- produces: wage-moments

### wage-table

The moments as a markdown table, one row per year, for pasting into the
paper. Four decimal places.

- consumes: wage-moments
- produces: wage-table
