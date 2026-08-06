// =============================================================
//  Edge Function : refresh-prices
//  Récupère le dernier cours de chaque asset (price_source != 'manual')
//  et l'écrit dans `prices`. Rafraîchit aussi les fx_rates utiles.
//
//  Déploiement :
//    supabase functions deploy refresh-prices --no-verify-jwt
//  Secrets nécessaires (Supabase les injecte, sauf SERVICE_ROLE à mettre) :
//    SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY
//  Planification : voir db/cron.sql (pg_cron + pg_net).
// =============================================================

import { createClient } from "https://esm.sh/@supabase/supabase-js@2";

type Asset = {
  id: string;
  currency: string;
  price_source: "yahoo" | "stooq" | "coingecko" | "twelvedata" | "manual";
  price_symbol: string | null;
};

const today = () => new Date().toISOString().slice(0, 10);

// --------- récupération d'un cours selon la source ---------

async function fetchYahoo(symbol: string): Promise<{ close: number; currency: string }> {
  const url =
    `https://query1.finance.yahoo.com/v8/finance/chart/${encodeURIComponent(symbol)}` +
    `?interval=1d&range=5d`;
  const r = await fetch(url, { headers: { "User-Agent": "Mozilla/5.0" } });
  if (!r.ok) throw new Error(`yahoo ${r.status}`);
  const j = await r.json();
  const meta = j?.chart?.result?.[0]?.meta;
  const px = meta?.regularMarketPrice;
  if (typeof px !== "number") throw new Error("yahoo: pas de prix");
  return { close: px, currency: meta?.currency ?? "EUR" };
}

async function fetchStooq(symbol: string): Promise<{ close: number; currency: string }> {
  const url = `https://stooq.com/q/l/?s=${encodeURIComponent(symbol)}&f=sd2t2ohlcv&h&e=csv`;
  const r = await fetch(url);
  if (!r.ok) throw new Error(`stooq ${r.status}`);
  const text = await r.text();
  // header puis une ligne : Symbol,Date,Time,Open,High,Low,Close,Volume
  const line = text.trim().split("\n").pop() ?? "";
  const cols = line.split(",");
  const close = Number(cols[6]);
  if (!isFinite(close) || close <= 0) throw new Error(`stooq: close invalide (${cols[6]})`);
  return { close, currency: "EUR" };
}

async function fetchCoingecko(id: string): Promise<{ close: number; currency: string }> {
  const url = `https://api.coingecko.com/api/v3/simple/price?ids=${encodeURIComponent(id)}&vs_currencies=eur`;
  const r = await fetch(url);
  if (!r.ok) throw new Error(`coingecko ${r.status}`);
  const j = await r.json();
  const close = j?.[id]?.eur;
  if (typeof close !== "number") throw new Error("coingecko: pas de prix");
  return { close, currency: "EUR" };
}

async function fetchPrice(a: Asset): Promise<{ close: number; currency: string }> {
  const sym = a.price_symbol!;
  switch (a.price_source) {
    case "yahoo": return await fetchYahoo(sym);
    case "stooq": return await fetchStooq(sym);
    case "coingecko": return await fetchCoingecko(sym);
    default: throw new Error(`source non gérée: ${a.price_source}`);
  }
}

// --------- taux de change (BCE via Frankfurter, gratuit, sans clé) ---------

async function refreshFx(supabase: any, currencies: string[]) {
  const foreign = [...new Set(currencies.map((c) => c.toUpperCase()))].filter(
    (c) => c && c !== "EUR",
  );
  if (foreign.length === 0) return { fx: 0 };
  const url = `https://api.frankfurter.app/latest?from=EUR&to=${foreign.join(",")}`;
  const r = await fetch(url);
  if (!r.ok) throw new Error(`frankfurter ${r.status}`);
  const j = await r.json();
  const rows = Object.entries(j?.rates ?? {}).map(([quote, rate]) => ({
    base: "EUR",
    quote,
    rate_date: j.date ?? today(),
    rate: rate as number,
  }));
  if (rows.length) {
    const { error } = await supabase.from("fx_rates").upsert(rows, {
      onConflict: "base,quote,rate_date",
    });
    if (error) throw error;
  }
  return { fx: rows.length };
}

// --------- handler ---------

Deno.serve(async (_req) => {
  const supabase = createClient(
    Deno.env.get("SUPABASE_URL")!,
    Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!,
  );

  const { data: assets, error } = await supabase
    .from("assets")
    .select("id, currency, price_source, price_symbol")
    .neq("price_source", "manual");

  if (error) {
    return new Response(JSON.stringify({ error: error.message }), {
      status: 500,
      headers: { "Content-Type": "application/json" },
    });
  }

  const results: Record<string, unknown>[] = [];
  const currencies: string[] = [];

  for (const a of (assets ?? []) as Asset[]) {
    if (!a.price_symbol) {
      results.push({ asset: a.id, ok: false, error: "price_symbol manquant" });
      continue;
    }
    try {
      const { close, currency } = await fetchPrice(a);
      currencies.push(currency);
      const { error: upErr } = await supabase.from("prices").upsert(
        { asset_id: a.id, price_date: today(), close, currency },
        { onConflict: "asset_id,price_date" },
      );
      if (upErr) throw upErr;
      results.push({ asset: a.id, ok: true, close, currency });
    } catch (e) {
      results.push({ asset: a.id, ok: false, error: String(e) });
    }
  }

  let fx = {};
  try {
    fx = await refreshFx(supabase, currencies);
  } catch (e) {
    fx = { error: String(e) };
  }

  const ok = results.filter((r) => r.ok).length;
  return new Response(
    JSON.stringify({ date: today(), prices_ok: ok, total: results.length, fx, results }, null, 2),
    { headers: { "Content-Type": "application/json" } },
  );
});
