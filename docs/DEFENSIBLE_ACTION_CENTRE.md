# Defensible Action Centre

This is the judge-facing differentiator in VASP Trace. The result screen answers four
questions before it allows a local request amount to be proposed:

1. **How much value reached this endpoint?** The envelope shows the confirmed
   case-attributed amount, the current model amount, unaccounted case value, and the
   maximum proposed local request amount.
2. **What could overturn the conclusion?** The challenge engine surfaces synthetic
   data, inferred endpoints, approximate wallet seeds, mixed balances, partial
   provider coverage, unresolved bridge boundaries, and incomplete local routing data.
3. **What is the next best evidence to collect?** Each challenge becomes an ordered,
   concrete investigator action, such as retrieving earlier balance history or
   collecting the matching destination bridge event.
4. **Can the case be routed locally?** A VASP readiness profile records supported
   chains, required packet fields, local contact route, template version, and reviewer
   state. It is local configuration, not a claim of official SAHYOG or VASP approval.

## Judge demonstration

1. Open the v2 evidence demo and point out `DO NOT ROUTE`: it is synthetic.
2. Open a recorded-real trace with a reviewed endpoint but no VASP readiness profile:
   the proposed request amount remains zero and the next action is to configure and
   review the local profile.
3. Register a reviewed profile for that VASP and show that the same immutable trace
   becomes `READY FOR LOCAL DRAFT` with a bounded amount.
4. Open the challenge list and explain that the system tells the investigator what
   would invalidate the conclusion instead of hiding uncertainty behind a percentage.
