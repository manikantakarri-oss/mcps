# GAM media planner

Read-only planner over a client's Google Ad Manager network, served as an MCP
tool for the Agent Portal's assistants.

- `gam.py`: Ad Manager access (positions, prices from line items, forecasts,
  and a delivery-based estimate when GAM has no forecast yet).
- `plan.py`: the budget arithmetic (max reach or balanced), tested offline by
  `python test_plan.py`.
- `server.py`: the five tools.

Credentials: a service account added as a user in the GAM network (role with
API access), its JSON key and the network code, set per client in the Portal
Deployer under **GAM connection**. They live only in the client's Databricks
secret scope and reach this app as `GAM_KEY_JSON` and `GAM_NETWORK_CODE`.
