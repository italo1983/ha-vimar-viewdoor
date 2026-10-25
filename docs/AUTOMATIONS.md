# Azioni, geofencing e comandi dall’auto

I due pulsanti dell’integrazione sono normali entità Home Assistant del dominio
`button`. Qualsiasi automazione può selezionare l’azione **Pulsante: premi** e
scegliere il cancelletto oppure il cancello carrabile. L’integrazione avvia il
video, aspetta le immagini, invia un solo impulso e chiude la propria sessione.
Non occorre aggiungere altre azioni per la telecamera.

Le entità non conoscono lo stato fisico aperto/chiuso. Una risposta positiva del
citofono indica accettazione del comando, non il movimento o la posizione finale.
Non usare un ciclo di tentativi per ripetere automaticamente l’apertura.

## Esempio di script

Creare uno script dalla UI, aggiungere **Pulsante: premi**, selezionare il pulsante
carrabile e assegnare un nome come “Apri cancello”. Non premere “Esegui” durante
la configurazione se non si desidera azionare fisicamente l’uscita.

In YAML, sostituire l’ID con quello effettivo del proprio pulsante:

```yaml
alias: Apri cancello
mode: single
sequence:
  - action: button.press
    target:
      entity_id: button.sostituire_con_il_proprio_pulsante
```

## Geofencing facoltativo

Il blueprint in `blueprints/automation/vimar_viewdoor/arrival_gate.yaml` permette
di scegliere persona/telefono, zona di arrivo, pulsante e un interruttore di
consenso. Copiarlo nella cartella `/config/blueprints/automation/vimar_viewdoor/`
e ricaricare i blueprint. In alternativa, importare il blueprint dall’URL del
file su GitHub. Non viene installato né attivato dal componente.

1. Configurare il telefono nell’app Home Assistant Companion, con localizzazione
   in background e rilevamento delle zone attivi.
2. Assicurare al telefono accesso ad Home Assistant anche fuori dal Wi-Fi di casa,
   per esempio tramite Home Assistant Cloud o una VPN già configurata.
3. Creare una zona di arrivo delle dimensioni adatte al percorso. Il GPS può
   aggiornarsi in ritardo: una zona non garantisce il punto esatto di apertura.
4. Creare un aiutante **Interruttore** chiamato “Consenti apertura all’arrivo” e
   lasciarlo inizialmente spento. Selezionarlo nel blueprint.
5. Creare l’automazione dal blueprint e selezionare il pulsante carrabile.
   L’apertura resta subordinata all’interruttore di consenso acceso.
6. Fare una prova supervisionata. Il blueprint limita le ripetizioni a una ogni
   cinque minuti e usa `mode: single`; non controlla veicolo, identità biometrica,
   ostacoli o posizione fisica del cancello.

Il solo ingresso nella zona non dimostra che si stia arrivando in auto. Per aprire
solo quando si guida, aggiungere nell’automazione una condizione basata sul
collegamento Bluetooth dell’auto o su un sensore appropriato del proprio telefono.
Nessuna posizione o dispositivo personale è incluso nel repository.

## Android Auto

Con l’app Companion collegata ad Home Assistant, Android Auto supporta direttamente
pulsanti e script. Aggiungere il pulsante/script ai preferiti dell’app per trovarlo
più facilmente sullo schermo dell’auto. La disponibilità e il numero di entità
visualizzabili dipendono dal veicolo. Usare dal veicolo richiede che il telefono
possa raggiungere Home Assistant.

## “Hey Google, apri il cancello”

Occorre prima collegare Home Assistant a Google Assistant, tramite Home Assistant
Cloud oppure l’integrazione manuale ufficiale. `ha.local` da solo non è un endpoint
pubblico raggiungibile da Google o dal telefono fuori casa.

Home Assistant può esporre pulsanti e script a Google come **scene**. Questo non
li trasforma in dispositivi `gate` e non aggiunge automaticamente il PIN previsto
per i dispositivi sicuri. Una scena che apre il cancello va quindi esposta solo
con una scelta esplicita del proprietario e a persone autorizzate. Per un vero
dispositivo `gate` con stato e richiesta PIN occorrono una modellazione adeguata
e, per lo stato fisico, un sensore: non inventare uno stato aperto/chiuso.

Dopo aver scelto il metodo e cosa esporre, configurare l’eventuale frase/routine in
Google Home e verificarla separatamente dal geofencing. Il componente non modifica
account Google, accesso remoto o configurazioni vocali durante l’installazione.

Fonti ufficiali:
- [Localizzazione Companion](https://companion.home-assistant.io/docs/core/location/)
- [Android Auto](https://companion.home-assistant.io/docs/android-auto/)
- [Google Assistant](https://www.home-assistant.io/integrations/google_assistant/)
