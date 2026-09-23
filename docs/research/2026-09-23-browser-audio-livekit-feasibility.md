# Ricerca di fattibilità: ascolto via browser con PIN, LiveKit vs Agora, server propri

**Data:** 2026-09-23
**Stato:** ricerca preliminare, nessuna modifica al codice. Da riprendere nella prossima sessione con i costi precisi.
**Spec di partenza:** `2026-09-23-browser-audio-background-spec-claudeai.md` (preparata con Claude.ai)

> I prezzi segnati come *verificati* sono stati letti sulle pagine ufficiali il 2026-09-23. Quelli *indicativi* sono stime da listino, da ricontrollare prima di decidere.

---

## 1. Contesto

- **2026-09-17:** scartata l'idea di un ospite via browser con Agora Web SDK (WebRTC dentro il tab). Motivo: gli ospiti aprono continuamente la fotocamera, Chrome va in background e l'audio si interrompe. Su Android economici il sistema può anche chiudere Chrome del tutto.
- **2026-09-23:** la spec di Claude.ai propone un meccanismo diverso. La guida resta su Agora, il server converte il canale in uno stream **HLS / LL-HLS** e l'ospite ascolta con un **`<audio>` nativo** più la Media Session API, entrando con il **PIN esistente** (niente QR code).

## 2. Valutazione della modalità browser (HLS)

### Perché è diversa dal tentativo scartato
Il sistema operativo tratta la riproduzione di un player nativo come Spotify o un podcast:
- **iOS Safari:** l'audio continua in background e compare nei controlli della schermata di blocco.
- **Android Chrome:** mentre riproduce audio, Chrome mostra una notifica multimediale con servizio in primo piano, quindi Android lo chiude molto meno facilmente.

La proposta affronta proprio il motivo del rifiuto del 17/09.

**Non è però dimostrato che basti:**
- **iOS:** scattare foto di solito non interrompe l'audio degli altri, **registrare un video sì**.
- **Android economici con poca RAM:** il rischio che il sistema chiuda Chrome si riduce ma non sparisce.

### Integrazione col PIN: fattibile
- Il PIN è già il nome del canale Agora: `app/api/routes.py` → `_extract_cname_from_session`.
- `POST /api/join-pin` può restituire, oltre al token Agora, un indirizzo dello stream HLS.
- Avvio e chiusura della conversione si agganciano ai punti che già esistono:
  - all'avvio della sessione (`/start-session`) si avvia il push verso RTMP;
  - alla chiusura (`/end-session` più lo scheduler) lo si ferma, insieme al kill switch `disband_channel_internal`.
- Le credenziali REST di Agora sono già presenti (`AGORA_CUSTOMER_ID` / `AGORA_CUSTOMER_SECRET`).

### Correzioni alla spec di Claude.ai
1. **Prodotto Agora giusto:** "Media Push" (convertitore RTMP), **non** "Cloud Recording", che registra su storage e non invia uno stream live.
2. **Limite di ospiti:** un indirizzo HLS fisso permetterebbe di ascoltare senza passare da `join-pin`, aggirando `max_listeners`. Serve un indirizzo **firmato, per ospite, con scadenza**.
3. **Bassa latenza:** NGINX-RTMP produce solo HLS classico (10–30 s). Per LL-HLS (2–4 s) servono **SRS** o un servizio gestito (Cloudflare Stream, Mux).
4. **Bug già noto, ancora aperto:** `license_crud.join_session_by_pin` conta tutti i Listener mai creati, non solo quelli connessi. Ogni riconnessione consuma un posto per sempre.

### Il rischio principale: la latenza
Gli ospiti stanno fisicamente vicino alla guida. Con 2–5 s di ritardo sentono prima la voce dal vivo e poi la stessa frase in cuffia, e le indicazioni ("guardate a sinistra") arrivano tardi. Può andare bene per gruppi grandi o ospiti lontani dalla guida. Per un tour a piedi classico è un peggioramento percepibile. Non ci sono domande e risposte in tempo reale.

### Costi della modalità browser
Esempio: tour di 30 ospiti più la guida per 90 minuti, circa 2.800 minuti di ascolto (2.700 per i soli ospiti).

| Voce | Tariffa | Tour di esempio |
|---|---|---|
| Oggi: tutti su Agora RTC | 0,99 $ / 1.000 min, primi 10.000 min al mese gratis *(indicativo)* | circa **2,80 $** |
| Agora Media Push, conversione audio con una sola guida | 1,99 $ / 1.000 min, **senza quota gratuita** *(verificato)* | circa 0,18 $ |
| Agora, minuti del convertitore (conta come un ascoltatore) | 0,99 $ / 1.000 min | circa 0,09 $ |
| Opzione A: Cloudflare Stream | 1 $ / 1.000 min ascoltati, ingest e codifica gratis *(verificato)* | circa 2,70 $ → **totale circa 3 $** |
| Opzione B: SRS su server nostro | circa 10–15 $/mese fissi su Railway, più 0,05 $/GB (64 kbps ≈ 30 MB/h per ospite) *(indicativo)* | circa 0,07 $ → **totale circa 0,35 $** più il costo fisso |

**Dubbi su Cloudflare Stream:** non è chiaro se accetti uno stream solo audio (potrebbe servire un fotogramma video fisso). Inoltre le dirette potrebbero essere registrate e conservate (5 $ / 1.000 min al mese).

**Media Push senza conversione:** con una sola guida forse si può evitare la conversione, ma l'audio Agora (Opus) va comunque convertito in AAC per RTMP/HLS. Probabilmente la conversione serve.

**Conclusione:** i costi non sono un problema. Con il server nostro la modalità browser costa circa un decimo di oggi per tour, perché gli ospiti non consumano minuti Agora.

## 3. LiveKit al posto di Agora

**Attenzione:** LiveKit usa WebRTC come Agora. Può sostituire Agora nell'app nativa, ma **non risolve** il problema del browser in background. Per il browser servirebbe comunque HLS, che LiveKit sa produrre con il servizio Egress.

### Prezzi LiveKit Cloud *(verificati su livekit.com/pricing, 2026-09-23)*

| Piano | Mese | Minuti WebRTC inclusi | Extra | Traffico incluso | Connessioni contemporanee |
|---|---|---|---|---|---|
| Build | 0 $ | 5.000 | 0,0005 $/min | 50 GB (poi 0,12 $/GB) | 100 |
| Ship | 50 $ | 150.000 | 0,0005 $/min | 250 GB (poi 0,12 $/GB) | 1.000 |
| Scale | 500 $ | 1.500.000 | 0,0004 $/min | 3 TB (poi 0,10 $/GB) | 5.000 |
| Enterprise | su misura | — | — | — | SLA contrattuale |

Egress (registrazione / HLS / RTMP): 60 / 600 / 8.000 min inclusi a seconda del piano, poi 0,001 $/min. Uptime dichiarato: 99,99%.

### Confronto mensile (tour da circa 2.800 min)

| Volume | Agora | LiveKit Cloud | LiveKit su server nostro UE |
|---|---|---|---|
| 20 tour/mese (circa 56.000 min) | circa 45 $ | 50 $ (piano Ship) | circa 20–40 € |
| 100 tour/mese (circa 280.000 min) | circa 265 $ | circa 115 $ | circa 20–40 € (forse un server più grande) |

- **Pochi tour:** costi simili, Agora costa quasi niente grazie alla quota gratuita.
- **In crescita:** Agora sale più in fretta. A 100 tour al mese LiveKit Cloud costa meno della metà, il server nostro circa un decimo.

### Latenza e affidabilità
- **Latenza:** uguale ad Agora, circa 150–300 ms (WebRTC + Opus).
- **LiveKit Cloud:** rete globale, 99,99% dichiarato, usato in produzione su larga scala (da verificare: OpenAI per la modalità vocale di ChatGPT).
- **Agora:** più anni di esperienza su reti mobili deboli grazie alla sua rete privata (SD-RTN). È un vantaggio reale per i tour all'aperto col 4G, difficile da misurare senza test sul campo.
- **Server nostro:** è un unico punto di rottura; se cade durante un tour, tutti i tour in corso restano senza audio.
- **Soluzione intermedia:** lo stesso SDK funziona con LiveKit Cloud e con il server nostro, cambia solo l'indirizzo. Si può usare il server nostro come principale e LiveKit Cloud come riserva automatica.

### Capacità *(benchmark ufficiale LiveKit)*
Su una macchina Google Cloud `c2-standard-16` (16 core), 10 publisher e 3.000 subscriber solo audio usano l'80% della CPU. Ogni stanza deve stare su un solo nodo. Per AirLink bastano 4 vCPU per diverse centinaia di ospiti contemporanei, da confermare con il load tester di LiveKit.

### Lavoro stimato per la migrazione
- **Backend:** i token Agora diventano token LiveKit (libreria Python `livekit-api`); il kill switch diventa la chiusura della stanza LiveKit. Il PIN resta e diventa il nome della stanza.
- **App:** riscrivere `useAgoraVoice.ts` con `@livekit/react-native`. Il servizio in primo piano Android resta. Richiede una nuova versione sugli store.
- **Stima:** circa 1–2 settimane più i test sul campo.

## 4. Server propri

### Comprare o affittare
- **Comprare hardware: sconsigliato.** Circa 600–1.500 € di hardware, più fibra aziendale con IP statico e molta banda in upload, più UPS e reperibilità. È più fragile e più caro.
- **Affittare in un datacenter: consigliato.**

### Messa in opera di LiveKit su un server nostro
- **Cosa serve:** un dominio, un certificato TLS, porte UDP aperte (di default 50000–60000), Redis e un TURN su porta 443 per le reti più restrittive. LiveKit fornisce un generatore di configurazione (docker compose con Caddy).
- **Tempo:** circa 1–2 giorni la prima volta.
- **Manutenzione:** qualche ora al mese tra aggiornamenti e monitoraggio.

### Costi per regione *(indicativi, per un server da 4 vCPU / 8 GB)*

| Regione | Fornitori | Costo/mese | Note |
|---|---|---|---|
| Europa | Hetzner (DE), OVH (FR) | circa 15–40 € | Traffico abbondante incluso, il più conveniente |
| USA | Hetzner (Virginia/Oregon), DigitalOcean, Vultr | circa 25–60 $ | Meno traffico incluso, ma sufficiente (circa 1 GB per tour) |
| Asia (Singapore, Tokyo) | Hetzner Singapore, Vultr, DigitalOcean | circa 40–70 $ | Traffico un po' più caro, per noi irrilevante |
| AWS / Google Cloud | ovunque | circa 120–150 $ più 0,09 $/GB | Il più caro; 100 tour al mese ≈ 100 GB ≈ 9 $ |
| Cina continentale | Alibaba Cloud, Tencent | server circa 50–100 $ | **Di fatto non praticabile**, vedi sotto |

**Il server va dove si fanno i tour**, non dove ha sede l'azienda. L'audio va dalla guida al server e torna agli ospiti, che sono nello stesso posto:
- tour in Italia con server in Germania: circa +30–50 ms, trascurabili;
- tour in Italia con server in USA: circa +250–300 ms tra andata e ritorno, si sentono.

**Cina:**
- ospitare in Cina continentale richiede una **licenza ICP**, che serve una società cinese o un partner locale;
- da Hong Kong o Singapore il Great Firewall rende WebRTC instabile;
- se un giorno servissero tour in Cina, la scelta giusta è **Agora**, che ha una rete propria dentro la Cina.

**Più regioni:** invece di gestire tre o quattro server in giro per il mondo, conviene **LiveKit Cloud**. Collega ogni ospite al server più vicino in automatico, allo stesso prezzo a minuto ovunque.

### Sovranità UE
LiveKit è open source (Apache 2.0). Installato su un server Hetzner in UE, toglierebbe di mezzo Agora, uno dei due problemi segnalati a NOI Techpark l'11/09. Resterebbe Railway (USA) per il backend, spostabile anch'esso in UE. NOI non ha più risposto; il contatto è probabilmente sfumato, ma il tema può tornare con altri clienti pubblici.

## 5. Schema consigliato, se e quando si procede
- **Server nostro UE** (Hetzner più LiveKit) per i tour in Italia ed Europa, con la conversione HLS per la modalità browser inclusa.
- **LiveKit Cloud** come riserva e per i tour nel resto del mondo, con lo stesso codice.
- **Cina:** solo Agora, se mai servirà.

**Quando conviene muoversi:**
- se i tour superano i 50–100 al mese;
- se un cliente richiede la sovranità UE;
- se il test sui telefoni (sotto) conferma che la modalità browser funziona.

Con i volumi attuali non c'è fretta di lasciare Agora solo per i costi.

## 6. Prossimi passi (prossima sessione)
1. **Costi precisi:** listini attuali di Hetzner, OVH, DigitalOcean e Vultr; tariffa Agora RTC del nostro account; volumi reali di minuti al mese dal DB di produzione (sessioni × ospiti × durata).
2. **Test sui telefoni** prima di qualsiasi lavoro sul backend: una pagina statica con PIN finto, uno stream LL-HLS da ffmpeg in locale (SRS o LiveKit Egress) e prove su un iPhone e un Android economico. Da provare: schermo bloccato 10 minuti, 20 foto, un video, WhatsApp. Misurare il ritardo.
3. **Cronometrare la latenza di Your Next Tours** con telefono bloccato, per verificare l'ipotesi HLS.
4. Correggere il bug di conteggio `max_listeners` in `join_session_by_pin`, indipendente da tutto il resto.

## Fonti
- [Agora Media Push pricing](https://docs.agora.io/en/media-push/overview/pricing)
- [Cloudflare Stream pricing](https://developers.cloudflare.com/stream/pricing/)
- [LiveKit pricing](https://livekit.com/pricing.md)
- [LiveKit benchmark](https://docs.livekit.io/transport/self-hosting/benchmark/)
- [LiveKit vs Agora cost analysis (Fora Soft)](https://www.forasoft.com/blog/article/livekit-vs-agora-cost-analysis)
- [Self-hosted LiveKit vs Cloud (Prodinit)](https://prodinit.com/blog/self-hosted-livekit-vs-livekit-cloud)
- [Hetzner Cloud](https://www.hetzner.com/cloud/)
