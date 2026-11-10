# thuis-eco-systeem – slimme energieplanner

Deze planner stuurt het huis zo dat het **zo goedkoop en zuinig mogelijk** draait,
zonder dat het comfort of het huis eronder lijdt. Hij is gemaakt voor een huis
met:

- **2 airco's** (lucht-lucht warmtepompen) die kunnen verwarmen en koelen
- **CV-ketel** op gas voor de rest van het huis
- **een paar zonnepanelen**
- **een thuisbatterij**
- **een dynamisch energiecontract** (stroomprijs per uur/kwartier)

Elk kwartier haalt de planner de stroomprijzen van vandaag en morgen op
(EnergyZero), de weersverwachting (Open-Meteo), en maakt een plan voor de
komende 24–36 uur. Daarna zet hij via Home Assistant de airco's, de
CV-thermostaat en de batterij in de juiste stand.

## Wat doet de planner?

### 1. Airco of CV – wie verwarmt het goedkoopst?

Per uur vergelijkt de planner de prijs van een kWh warmte:

| Bron  | Kosten per kWh warmte                         | Voorbeeld              |
|-------|-----------------------------------------------|------------------------|
| CV    | gasprijs ÷ (9,77 kWh/m³ × 90% rendement)      | €1,35/m³ → **€0,15**   |
| Airco | stroomprijs ÷ COP (afhankelijk van buitentemp)| €0,25 ÷ 3,8 → **€0,07**|

Een airco is dus meestal **2× zo goedkoop** als gas. Daarom:

- verwarmen de airco's waar ze kunnen, en gaat de **CV-thermostaat 1,5 °C omlaag**
  zodat de ketel alleen de kamers zonder airco bijwarmt;
- schakelt het terug naar **CV** in de zeldzame uren dat stroom extreem duur is,
  of als het zo hard vriest dat de airco's slecht presteren.

### 2. Slim voorverwarmen

Het huis slaat warmte op in muren en vloeren. In de **goedkoopste uren** gaan
de airco's 1 °C hoger (bv. rond het middaguur en vlak voor het opstaan), in de
**duurste uren** (de avondpiek) 0,5 °C lager. 's Nachts wordt niet onnodig
gestookt. In de zomer werkt het omgekeerd: voorkoelen als stroom goedkoop is.

### 3. Batterij: optimaal laden en ontladen

De planner rekent met *dynamisch programmeren* het goedkoopste laadschema uit
over de hele horizon, rekening houdend met het verbruik (incl. airco's), de
verwachte zonne-opbrengst, het rendement en de slijtage. De batterij krijgt één
van vier standen:

| Stand            | Wanneer                                              |
|------------------|------------------------------------------------------|
| `laden_net`      | goedkoop uur → bijladen uit het net                  |
| `vasthouden`     | energie bewaren voor een duurder uur straks          |
| `ontladen_net`   | piekprijs → huis voeden en evt. terugleveren         |
| `zelfconsumptie` | normaal: zonne-overschot opslaan, tekort aanvullen   |

### 4. Goed voor het huis (en de apparaten)

- **Batterij blijft tussen 10% en 95%** en cyclet alleen als het echt iets
  oplevert (slijtagekosten zitten in de berekening) → langere levensduur.
- **Geen pendelen**: setpoints veranderen maximaal 1 °C per stap, de CV wordt niet
  uitgezet maar alleen iets lager gezet, zodat koude kamers niet te ver afkoelen
  (vocht en schimmel).
- **Vochtmelding** in Home Assistant: boven 65% luchtvochtigheid krijg je een seintje
  om te ventileren of de airco op *drogen* te zetten.
- **Negatieve stroomprijs** → batterij laden in plaats van terugleveren.

### 5. Let op: saldering stopt op 1 januari 2027

Tot en met 2026 is teruggeleverde stroom evenveel waard als ingekochte stroom.
Vanaf 2027 krijg je voor teruglevering alleen nog de kale marktprijs (en soms
moet je zelfs betalen). De planner schakelt automatisch om op basis van
`saldering_tot` in de config: vanaf dan wordt zonnestroom **zoveel mogelijk zelf
gebruikt of opgeslagen** in plaats van teruggeleverd. De batterij wordt daardoor
juist waardevoller.

## Aan de slag

Benodigd: Python 3.11 of nieuwer (geen extra pakketten), en bij voorkeur
[Home Assistant](https://www.home-assistant.io/) met de airco's, de
CV-thermostaat en de batterij gekoppeld.

```bash
cp config.voorbeeld.toml config.toml   # en vul jullie eigen gegevens in
python3 -m energieplanner plan --demo  # proefdraaien met nep-data
python3 -m energieplanner plan --soc 0.4   # echt plan met live prijzen en weer
```

Voorbeeld van de uitvoer (demo, novemberdag):

```
tijd         prijs  buiten   zon  warmte  bron       CV  airco setpoints batterij         SoC    net
Tue 04:00  0.199    2.6°  0.00   2.59  airco   15.5°  17.0/17.0       ⬆ laden         4.7   3.14
Tue 08:00  0.315    5.1°  0.00   2.68  airco   18.5°  19.5/19.5       ⬇ ontladen      2.2  -1.61
Tue 12:00  0.226    8.5°  0.35   2.07  airco   18.5°  21.0/21.0       ⬆ laden         2.2   2.11
Tue 18:00  0.382    8.5°  0.00   2.07  airco   18.5°  19.5/19.5       ⬇ ontladen      3.0  -0.98
...
Kosten met slimme sturing : €   9.50
Kosten zonder sturing     : €  15.05  (alles op CV, batterij alleen zon opslaan)
```

### Koppelen aan Home Assistant

1. Maak in Home Assistant een *long-lived access token* (profiel → Beveiliging).
2. Zet het in een omgevingsvariabele: `export HA_TOKEN=...`
3. Vul in `config.toml` de entity-namen van de airco's en de CV-thermostaat in.
4. Kopieer `homeassistant/packages/energieplanner.yaml` naar `/config/packages/` en
   pas de batterij-acties aan op jullie omvormer.
5. Eerst droog testen: `python3 -m energieplanner stuur --droog`
6. Laat het elk kwartier draaien, via de automatisering in het package of met cron:

   ```cron
   */15 * * * * cd ~/thuis-eco-systeem- && HA_TOKEN=... python3 -m energieplanner stuur --soc $(...)
   ```

Met `input_boolean.energieplanner_actief` zet je de sturing in één klik uit.

### De belangrijkste instellingen

- **`warmteverlies_w_per_k`** – hoeveel watt het huis verliest per graad verschil.
  Schatting: jaarlijks gasverbruik (m³) × 0,105 ≈ W/K. Bij 1.400 m³ is dat ~150 W/K.
- **`dekking`** per airco – welk deel van de warmtevraag die airco kan leveren.
  Een airco in de woonkamer van een tussenwoning dekt vaak 40–50%.
- **`cop_7c`** – staat in de datasheet (gebruik anders de SCOP, vaak 4,0–4,6).
- **`slijtage_eur_per_kwh`** – aanschafprijs batterij ÷ (capaciteit × ~6.000 cycli).
- **`energiebelasting`, `inkoop_opslag`** – check je contract en het actuele tarief.

## Projectstructuur

```
energieplanner/
  bronnen.py        prijzen (EnergyZero) en weer (Open-Meteo), plus demo-data
  warmte.py         COP-model, airco-vs-CV keuze, voorverwarmen/voorkoelen
  batterij.py       optimaal laadschema (dynamisch programmeren)
  planner.py        alles samen + vergelijking met 'niet slim sturen'
  homeassistant.py  plan doorzetten naar Home Assistant
homeassistant/packages/energieplanner.yaml   helpers en automatiseringen
tests/                                         python3 -m unittest
```
