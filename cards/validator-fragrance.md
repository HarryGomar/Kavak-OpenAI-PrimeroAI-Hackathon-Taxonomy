# Validator card: fragrance

The validator labels a listing blind. It never sees the pipeline's answer or the reviewer's label. It answers with one
path, brand first: `[Brand, line?, product, flanker?]`, or `null` when the title names no product.

## v1 (Loop B V1, 2026-11-09)

- The product is the name the title or the catalog page gives, without size, concentration, audience or edition words.
- A flanker sits under its line when the brand's menu shows the line: Guilty > Guilty Elixir, Sugar > Sugar Caramel
  Chocolate Macaron.
- A body mist, oil or travel spray of a named scent stays on the scent.
- A catalogue number is not a name ("Silky Veil of Santal 36" > Silky Veil of Santal).

## v2: changes from V1's review (reviewer: Pedia; 3 of 19 flags wrong, 1 of 6 spot checks wrong)

- **Sets:** a set or kit of different scents is the node `Gift Set`, under the brand. A set of one scent's forms or
  sizes is `Gift Set` under that scent. Don't name the set ("Minis Gift Set", "Coast to Coast Gift Set"); the
  reviewer's tree has one set node per parent. (V1: Juicy Couture minis kit, Goldfield & Banks travel trio, Oakcha mini
  set, Dossier advent calendar.)
- **Couple sets:** a set of two products of one line goes on the first named product, not on a new set node.
  (V1: Armaf Club de Nuit Intense couple combo.)
- **Unchanged:** the validator was right on 12 of the 16 pipeline errors V1 found. Most were names seen once, which the
  pipeline sent to the agent.
