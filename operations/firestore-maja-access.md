# Maja Firestore access — 2026-09-08

The owner's Firebase Console screenshot showed the default database still using
the public test rule `request.time < timestamp.date(2026, 9, 8)` for all documents.
Once this date passed, every browser read was denied, including all five
calculator collections. Firebase custom-token login still succeeded. The earlier
calculator session-isolation fix addressed cross-tab authentication, not this
expired rule.

`firestore.maja.rules` replaces the expired rule with access based on the existing
Railway-issued `sppg_site` and `sppg_role` claims, without a calendar expiry:

- MAJA and OWNER tokens scoped to MAJA can use Maja calculator documents.
- Only OWNER tokens scoped to MAJA can use Maja finance ledger documents,
  including the metadata document, inventory, shareholders and nested backups.
- Anonymous users, other sites and unmatched paths have no access.

The Maja accountant now authenticates with Firebase before mounting its ledger
UI; previously that route relied on the public test rule. Cemplang uses its
existing rules and login flow. Data paths and stored documents are unchanged.

## Release

1. Deploy the accompanying application commit on Railway first.
2. In Firebase project `sppg-finance-gpt`, select Firestore database `(default)`.
3. Replace the complete Rules editor contents with `firestore.maja.rules`, then
   Publish. Alternatively, an authorized Firebase CLI session can use
   `firebase deploy --only 'firestore:(default)' --project sppg-finance-gpt`.
4. Reload Maja calculator and accountant after rule propagation.

Railway deployment does **not** publish Firebase rules. Rules were prepared from
the supplied screenshot; console publication and live authenticated verification
remain separate from the application release. Local regression tests cover token
scoping and waiting for authentication; they do not execute the Firestore rules
engine. Firebase validates the rules during publication.

Reference: https://firebase.google.com/docs/rules/manage-deploy
