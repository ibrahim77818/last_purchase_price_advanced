# Last Purchase Price Advanced (Odoo 16 Community & Enterprise)

Price intelligence for purchasing: every PO line shows the last confirmed
purchase price, normalized to the line's unit of measure and currency, with a
variance and an up/down signal. A **Vendor Price Stability** report measures
how stable each vendor's prices are (Pivot, Graph, List, Excel, PDF).

## Configuration
*Purchase › Configuration › Settings › Price Intelligence* (per company)

| Setting | Default | Effect |
|---|---|---|
| Advanced Last Purchase Price | off | Shows the intelligence columns on PO lines |
| Last Price Source | Same Vendor | Same Vendor (commercial partner) or Any Vendor |
| Neutral Variance Band (%) | 0 | \|variance\| ≤ band is flagged *Unchanged* |
| Stable / Volatile Threshold (CV %) | 2 / 10 | Stability classes of the report |

## On purchase order lines
`Last Price` (normalized), `Var. %`, `Signal` (Price Up / Price Down /
Unchanged / No History). Optional columns: last UoM, last currency, historical
currency rate, last PO, last purchase date, plus a button opening the
product's price stability analysis. The line form (mobile) shows the same data
as coloured badges.

*Last confirmed price* = most recent order in state Purchase Order / Locked,
ranked by confirmation date, excluding the order being edited, lines with a
zero quantity or price, and section/note lines.

### Normalization
1. Same currency as the current order → the historical price is used as is.
2. Different currency → historical price ÷ rate stored on the historical order
   (→ company currency) × rate stored on the current order.
3. UoM → converted with `uom.uom._compute_price` to the line's UoM.
4. Rounded once, at the end, to the *Product Price* precision; the variance is
   computed on that rounded value, so equal prices never show a ±0.00 % signal.

## Vendor Price Stability
*Purchase › Reporting › Vendor Price Stability* — pivot (vendor × product ×
quarter), graph (price over time per vendor) and list. Each confirmed line is
priced per product UoM in company currency and compared with the previous
purchase of the same product from the same vendor (trend: First Purchase,
Price Up, Price Down, Stable). Filters: trend, fluctuation > 5 % / 10 %,
purchase date; group by vendor, product, category, trend, buyer, company,
order currency.

*Purchase › Reporting › Vendor Price Stability (PDF / Excel)* — filter by
period, vendors, products, categories, companies, price trend (Rising /
Falling / Flat), stability (Stable / Moderate / Volatile) and minimum number
of purchases, then print a landscape QWeb PDF or export an Excel workbook
(summary sheet with conditional formatting + optional line-by-line price
history). Per vendor/product: purchases, first/last/min/max/avg price,
standard deviation, CV %, spread %, change %, increases/decreases, trend,
stability and a 0–100 score (100 = no fluctuation, 50 = volatile threshold).

Also available from the product form (*Price Stability* smart button).

## Arabic / RTL
`i18n/ar_001.po` covers every field, selection, view, menu, report and Python
string. The PDF uses Odoo's RTL asset bundle (no hard-coded direction rules)
and the Excel sheets switch to right-to-left when the user's language is RTL.

## Performance
* One SQL query resolves the last price of **all** lines being computed (a
  300-line PO = one query); window functions keep only the two most recent
  orders per key. A partial index on `purchase_order_line(product_id,
  order_id)` is created on install.
* Measured on PostgreSQL 16 with 1 M order lines / 100 k orders: a 500-line
  PO is resolved in ~25 ms (same-vendor scope) and ~130 ms (any-vendor scope).
* The analysis is a SQL view; Excel/PDF statistics are aggregated in SQL
  (`AVG`, `STDDEV_SAMP`, ordered `ARRAY_AGG`) with record rules applied.

## Comparison of alternative RFQs
The module depends on *Purchase Agreements* (`purchase_requisition`) and adds
Last Price / Var. % / Signal / Last Vendor to the *Compare Product Lines*
view of alternative RFQs.

## Tests
```
odoo-bin -d <db> -i last_purchase_price_advanced --test-enable --stop-after-init \
         --test-tags /last_purchase_price_advanced
```
