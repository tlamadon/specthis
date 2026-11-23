---
title: Wages
---

# Wages

The numbers the paper prints, made from a four-worker payroll extract.

### raw-wages

Payroll extract, four workers, 2019–2020. One row per worker-year, wages
in nominal euros. A negative wage in 2020 is a known coding error in the
source system — never repair it upstream.

- produces: data/raw/wages.csv

### wage-moments

Mean and variance of **log** wages, by year, over the positive wages
only. The variance is the population form (divide by n), not the sample
form.

- consumes: raw-wages
- produces: wage-moments

### moments-table

The moments as a LaTeX tabular the paper inputs: one row per year —
year, n, mean log wage, variance — at four decimal places.

- consumes: wage-moments
- produces: moments-table
