-- Correct only untouched upgrade seeds. Archive/finalize updated_at is not a
-- number-selection event. Operator anchors written after v043 remain intact.
insert into document_number_anchors(site,namespace,full_number,owner_key,selected_at)
select distinct on(c.site,c.namespace)
  c.site,c.namespace,c.full_number,c.owner_key,c.created_at
from document_number_serials c
left join generated_accountant_documents d
  on d.site=c.site and d.document_type=c.namespace and c.owner_key='DOC:'||d.id::text
left join lpdh_daily_state s
  on s.site=c.site and c.namespace='LPDH' and c.owner_key='DAY:'||s.service_date::text
where c.serial is not null and (
  lower(btrim(d.document_number))=lower(btrim(c.full_number)) or
  lower(btrim(s.data->>'lpdhNumber'))=lower(btrim(c.full_number)))
order by c.site,c.namespace,c.created_at desc,
  coalesce(d.created_at,s.service_date::timestamptz,c.created_at) desc,c.owner_key desc
on conflict(site,namespace) do update
set full_number=excluded.full_number,owner_key=excluded.owner_key,selected_at=excluded.selected_at
where document_number_anchors.selected_at <= (
  select applied_at from schema_migrations
  where migration_name='schema/document_routine_archives_v043.sql');
