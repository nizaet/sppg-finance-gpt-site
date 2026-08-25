-- BGN semantics: bank approval is the payment confirmation.  Existing
-- approved Makers therefore become PAID and receive an auditable receipt.
insert into bgn_receipts(bgn_maker_id,destination_account_type,amount,received_at,evidence_uri)
select m.id,'SPPG',m.amount,coalesce(a.approved_at,m.created_at,now()),a.evidence_uri
from bgn_makers m
join lateral (
  select * from bgn_approvals x
  where x.bgn_maker_id=m.id
  order by x.created_at desc,x.id desc limit 1
) a on true
left join bgn_receipts r on r.bgn_maker_id=m.id
where upper(a.status)='APPROVED' and r.id is null;

update bgn_makers m
set status='PAID'
where exists (
  select 1 from bgn_approvals a
  where a.bgn_maker_id=m.id and upper(a.status)='APPROVED'
);
