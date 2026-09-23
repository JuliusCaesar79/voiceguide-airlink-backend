# Ascolto via browser con PIN, funzionante in background

Spec tecnica: come far reggere l'audio della guida in un browser mobile anche quando l'ospite passa a un'altra app (fotocamera, WhatsApp, ecc.), sul modello di ciò che già fa l'app nativa AirLink con Agora.

---

## 1. Perché oggi Agora via browser si interrompe in background

Agora Web SDK (come tutto WebRTC) tiene viva la connessione tramite JavaScript in esecuzione nel tab. iOS Safari e Chrome/Android sospendono l'esecuzione JS di un tab non attivo per risparmiare batteria: la connessione peer-to-peer cade quasi subito quando l'utente cambia app.

Questo è un limite di piattaforma, non un bug della vostra implementazione: non esiste oggi un modo per far girare WebRTC "vero" a bassa latenza in un tab browser in background su iOS/Android in modo affidabile.

## 2. Perché WhatsApp non ha questo problema

Le chiamate WhatsApp non girano in un browser: sono un'app nativa con permessi di sistema (`Background Modes: Audio` su iOS, foreground service + CallKit su Android) che il sistema operativo tratta come processo autorizzato a restare attivo. Un tab web non ha questi privilegi, qualunque cosa contenga.

## 3. Come Your Next Tours ottiene (probabilmente) un risultato simile da browser

Ipotesi più solida, coerente con quanto riscontrato testando la loro app: **non usano WebRTC lato ospite**, ma uno streaming audio "media nativo" del browser:

- Il flusso guida viene ingerito (es. via RTMP dal loro backend) e ridistribuito come **HLS** (HTTP Live Streaming) o un semplice stream Icecast/Shoutcast-style.
- Il lato ospite non è un tab JS che orchestra WebRTC: è un tag `<audio>` HTML5 nativo puntato a quell'URL di streaming, eventualmente esposto anche via **Media Session API** per i controlli sulla lock screen.
- iOS e Android trattano un elemento `<audio>`/`<video>` nativo come sessione di "media playback" di sistema (la stessa categoria di Spotify Web o un podcast da browser): questa sessione **sopravvive al background** per policy di sistema, mentre l'esecuzione JS generica no.

Il prezzo di questa scelta è la **latenza**: HLS standard ha tipicamente 15-45 secondi di ritardo lato CDN; anche una pipeline ottimizzata (chunk più corti, Low-Latency HLS) resta nell'ordine di qualche secondo, mai i ~200ms di WebRTC/Agora.

**Verifica pratica consigliata**: cronometrare lo scarto voce-guida/audio-ricevuto sul loro sistema con telefono bloccato. Se c'è un ritardo percepibile (anche solo 2-4 secondi), l'ipotesi è confermata.

## 4. Architettura proposta per AirLink (modalità browser opzionale)

Obiettivo: un secondo canale di ascolto, via browser con PIN, pensato per chi non vuole installare l'app, che regga background/multitasking. Non sostituisce l'app nativa (che resta la modalità premium a bassissima latenza), è un fallback.

```
Guida (app nativa, Agora RTC)
        │
        ▼
Backend AirLink
        │  Agora Cloud Recording / RTMP push, oppure captazione lato server
        ▼
Media server (es. FFmpeg / NGINX-RTMP / SRS / Cloudflare Stream)
        │  transcodifica RTMP → HLS (segmenti .ts + manifest .m3u8)
        ▼
CDN / storage con bassa latenza (LL-HLS se possibile)
        │
        ▼
Pagina ospite (PIN → join → <audio> nativo + Media Session API)
```

### Componenti da valutare

1. **Bridge Agora → RTMP**: Agora offre "Cloud Recording" e funzioni di push-stream/restreaming che possono portare il canale RTC verso un endpoint RTMP, senza dover reingegnerizzare la parte guida.
2. **Conversione RTMP → HLS**: FFmpeg o NGINX con modulo RTMP possono generare i segmenti HLS; in alternativa un servizio gestito (Cloudflare Stream, Mux, AWS Elemental) evita di mantenere infrastruttura di transcodifica.
3. **Low-Latency HLS (LL-HLS)**: riduce il ritardo a pochi secondi invece di decine; supportato nativamente da Safari su iOS, richiede libreria player (es. hls.js) su Chrome/Android.
4. **Pagina ospite**:
   - join con PIN come oggi;
   - tag `<audio>` nativo (non Web Audio API/WebRTC) puntato al manifest HLS;
   - integrazione **Media Session API** (`navigator.mediaSession`) per titolo/controlli su lock screen e continuità in background;
   - su iOS, verificare che la sessione parta da un gesto utente esplicito (richiesto per lo sblocco dell'autoplay).
5. **Fallback**: se HLS/LL-HLS non è disponibile nel browser, mostrare avviso e suggerire l'app nativa per la modalità a bassa latenza.

## 5. Trade-off da comunicare internamente

| | App nativa (attuale) | Browser + PIN (proposto) |
|---|---|---|
| Latenza | ~200ms (Agora RTC) | 2-15s (LL-HLS/HLS) |
| Background/multitasking | Sì, già funzionante | Sì, via media session nativa |
| Installazione richiesta | Sì | No |
| Complessità infrastrutturale aggiuntiva | Nessuna | Bridge RTMP + transcodifica + CDN |
| Casi d'uso ideali | Tour con Q&A, interazione stretta guida-gruppo | Ospiti occasionali, gruppi grandi, no-install |

## 6. Prossimi passi consigliati

1. Verificare le opzioni di restreaming/Cloud Recording effettivamente disponibili sul piano Agora attualmente in uso.
2. Prototipo minimo: un canale broadcast → RTMP → FFmpeg → HLS locale, testato su iOS Safari e Chrome Android con schermo bloccato/fotocamera aperta, misurando latenza reale.
3. Decidere se posizionare la modalità browser come alternativa gratuita "entry level" o come opzione per grandi gruppi/eventi dove l'installazione app è un attrito.
