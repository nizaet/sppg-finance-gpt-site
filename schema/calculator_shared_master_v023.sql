-- Shared calculator master data v0.23.
-- Prices, gramasi, recipes, and bumbu are mirrored to both calculator targets.
-- Daily plans remain site-specific.

alter table calculator_import_events
  drop constraint if exists calculator_import_events_data_type_check;
alter table calculator_import_events
  add constraint calculator_import_events_data_type_check
  check (data_type in ('PRICES','GRAMASI','RECIPES','BUMBU','DAILY_PLANS'));

alter table calculator_master_catalog
  drop constraint if exists calculator_master_catalog_source_type_check;
alter table calculator_master_catalog
  add constraint calculator_master_catalog_source_type_check
  check (source_type in ('PRICE','GRAMASI','RECIPE','RECIPE_INGREDIENT','BUMBU','PLAN_ITEM'));
