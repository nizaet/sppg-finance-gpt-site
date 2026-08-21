-- Durable external memory for Custom GPT operational conversations v0.31
-- Every turn can be archived, while only evidence-backed durable facts are
-- promoted into reusable knowledge. Raw conversation evidence is append-only.

create table if not exists llm_conversation_events (
  id bigserial primary key,
  source_key text not null unique,
  conversation_ref text not null,
  turn_ref text,
  site text,
  vendor_code text,
  user_message text not null,
  assistant_summary text,
  action_context jsonb not null default '{}'::jsonb,
  actor text not null default 'chatgpt',
  created_at timestamptz not null default now(),
  check (site is null or site in ('MAJA','CEMPLANG'))
);

create index if not exists idx_llm_conversation_events_scope_time
  on llm_conversation_events(site, vendor_code, created_at desc);

create index if not exists idx_llm_conversation_events_conversation
  on llm_conversation_events(conversation_ref, created_at desc);

create table if not exists llm_learned_knowledge (
  id bigserial primary key,
  knowledge_key text not null unique,
  scope_type text not null default 'GLOBAL',
  site text,
  vendor_code text,
  topic text,
  statement text not null,
  normalized_statement text not null,
  knowledge_kind text not null,
  status text not null default 'CANDIDATE',
  confidence numeric(6,5) not null default 1,
  evidence_event_id bigint references llm_conversation_events(id),
  evidence_count integer not null default 1,
  metadata jsonb not null default '{}'::jsonb,
  first_seen_at timestamptz not null default now(),
  last_seen_at timestamptz not null default now(),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  check (scope_type in ('GLOBAL','SITE','VENDOR','ITEM','WORKFLOW')),
  check (site is null or site in ('MAJA','CEMPLANG')),
  check (knowledge_kind in ('USER_EXPLICIT','USER_CORRECTION','ACTION_CONFIRMED','ASSISTANT_INFERENCE')),
  check (status in ('CONFIRMED','CANDIDATE','REJECTED','SUPERSEDED')),
  check (confidence >= 0 and confidence <= 1)
);

create index if not exists idx_llm_learned_knowledge_scope
  on llm_learned_knowledge(status, site, vendor_code, last_seen_at desc);

create index if not exists idx_llm_learned_knowledge_topic
  on llm_learned_knowledge(topic, status, last_seen_at desc);

create index if not exists idx_llm_learned_knowledge_search
  on llm_learned_knowledge using gin (
    to_tsvector('simple', coalesce(topic,'') || ' ' || coalesce(statement,''))
  );
