---
title: The paper
---

# The paper

What the manuscript prints, and what backs it. Every entry here is an
**exhibit**: it produces nothing, and its vouch says the document
describes the result the way the entries it consumes define it.

### tab-moments

Table 1: the log wage moments by year, laid out as `moments-table`
renders them. The caption and note must describe the procedure
`wage-moments` defines — non-positive wages dropped, the population
variance of log wages.

- consumes: wage-moments, moments-table
- appears: paper#tab:moments

### prop-units

Proposition 1: the variance of log wages the paper reports does not
depend on the currency unit. True of the population variance of logs
that `wage-moments` defines, since rescaling every wage adds the same
constant to every log.

- consumes: wage-moments
- appears: paper#prop:units
