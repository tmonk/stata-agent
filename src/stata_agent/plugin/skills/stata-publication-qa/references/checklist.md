# Publication QA Checklist

For tables:

- coefficient labels clear enough for readers
- sample size consistent across specifications
- clustering and FE notes explicit
- fit statistics present when expected
- rounding and notation consistent

For figures:

- title, subtitle, notes, axis labels, legends
- scale choices do not obscure interpretation
- graph defaults do not look exploratory
- colors and categories remain legible when printed

Use `stata results --return e` to verify coefficients and standard errors, and `stata graph export` to produce reviewable figure files.
