import json
import os
import threading
import time
import sys

import paho.mqtt.client as mqtt
from mcp.server.fastmcp import FastMCP

MQTT_HOST = os.environ.get("US_MQTT_HOST", "localhost")
MQTT_PORT = int(os.environ.get("US_MQTT_PORT", "1883"))
TIM = os.environ.get("US_TIM", "tim18")

mcp = FastMCP("us-uredjaji")

mqtt_client = mqtt.Client(
    callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
    client_id=f"mcp-{TIM}-{os.getpid()}",
)

posljednje_poruke = {}
brava = threading.RLock()
def on_connect(client, userdata, flags, reason_code, properties):
    if reason_code == 0:
        print(f"[MQTT] Povezan na {MQTT_HOST}:{MQTT_PORT}", file=sys.stderr)
        client.subscribe("vucko/tasmota/dht11")
        client.subscribe("vucko/esp32/senzori")
        client.subscribe("vucko/esp32/komande")
        client.subscribe("vucko/esp32/matrica")
    else:
        print(f"[MQTT] Greska pri povezivanju, kod: {reason_code}", file=sys.stderr)


def on_message(client, userdata, msg):
    payload_str = msg.payload.decode("utf-8", errors="replace")
    try:
        payload_data = json.loads(payload_str)
    except json.JSONDecodeError:
        payload_data = payload_str

    with brava:
        posljednje_poruke[msg.topic] = {
            "payload": payload_data,
            "vrijeme": time.time(),
        }
    print(f"[MQTT] {msg.topic} -> {payload_str}", file=sys.stderr)

mqtt_client.on_connect = on_connect
mqtt_client.on_message = on_message


def on_disconnect(client, userdata, disconnect_flags, reason_code, properties):
    if reason_code != 0:
        print(f"[MQTT] Nepredvidjeno prekidanje: {reason_code}", file=sys.stderr)
        print(f"[MQTT] Pokusaj ponovne konekcije...", file=sys.stderr)
        client.reconnect()

mqtt_client.on_disconnect = on_disconnect

try:
    mqtt_client.connect(MQTT_HOST, MQTT_PORT, keepalive=60)
    mqtt_client.loop_start()
    print(f"[MQTT] Pokusaj konekcije na {MQTT_HOST}:{MQTT_PORT}", file=sys.stderr)
    time.sleep(2)
except Exception as e:
    print(f"[MQTT] GRESKA pri konekciji: {e}", file=sys.stderr)

zahtjev_tajmeri = {}


def resetuj_tajmer(topic: str):
    with brava:
        zahtjev_tajmeri[topic] = None


def provjeri_timeout(topic: str, timeout_sekundi: int = 60) -> tuple[bool, str]:
    with brava:
        if zahtjev_tajmeri.get(topic) is None:
            zahtjev_tajmeri[topic] = time.time()
            return (False, "Cekam odgovor rovera (~2 s).")

        vrijeme_pocetka = zahtjev_tajmeri[topic]
        proslost_vremena = time.time() - vrijeme_pocetka
        if proslost_vremena > timeout_sekundi:
            resetuj_tajmer(topic)
            return (True, f"Timeout: nema odgovora nakon {int(proslost_vremena)} s.")

        sekundi_ostalo = timeout_sekundi - int(proslost_vremena)
        return (False, f"Cekam odgovor rovera, preostalo {sekundi_ostalo} s.")


@mcp.tool()
def zahtjevajOcitavanjeDHT(zahtjeva: str) -> str:
    """Salje roveru zahtjev za ocitavanje DHT11 senzora.
    Rezultat se cita pozivom ocitajAtmosferskeParametre() nakon nekoliko sekundi.

    zahtjeva: "temperatura", "vlaga" ili "oboje"
    """
    if not mqtt_client.is_connected():
        return "Greska: MCP server nije povezan na MQTT broker."

    response_topic = "vucko/tasmota/dht11"
    topic = "vucko/esp32/komande"

    with brava:
        if response_topic in posljednje_poruke:
            del posljednje_poruke[response_topic]

    resetuj_tajmer(response_topic)
    naredba = {"komanda": "zahtjev_dht", "zahtjeva": zahtjeva}
    mqtt_client.publish(topic, json.dumps(naredba))
    return f"Zahtjev za {zahtjeva} poslan."


@mcp.tool()
def ocitajAtmosferskeParametre() -> str:
    """Vraca temperaturu i vlagu nakon poziva zahtjevajOcitavanjeDHT().
    Ako odgovor jos nije stigao, vraca status cekanja. Nakon 60 s vraca timeout
    i tada treba poslati novi zahtjev.
    """
    if not mqtt_client.is_connected():
        return "Greska: MCP server nije povezan na MQTT broker."

    topic = "vucko/tasmota/dht11"
    with brava:
        zapis = posljednje_poruke.get(topic)

    if zapis is None:
        je_timeout, poruka = provjeri_timeout(topic, timeout_sekundi=60)
        return poruka

    resetuj_tajmer(topic)

    if isinstance(zapis['payload'], dict):
        temp = zapis['payload'].get('temperatura', 'N/A')
        vlaga = zapis['payload'].get('vlaga', 'N/A')
    else:
        temp = 'N/A'
        vlaga = 'N/A'

    return f"Temperatura: {temp} C, vlaga: {vlaga} %"


@mcp.tool()
def zahtjevajNavigacijskePodatke(zahtjeva: str) -> str:
    """Salje roveru zahtjev za udaljenost od prepreke (ultrazvucni senzor) i ugao (ziroskop).
    Rezultat se cita pozivom ocitajStatuseVozila().

    zahtjeva: "udaljenost", "ugao" ili "oboje"
    """
    if not mqtt_client.is_connected():
        return "Greska: MCP server nije povezan na MQTT broker."

    response_topic = "vucko/esp32/senzori"
    topic = "vucko/esp32/komande"
    with brava:
        if response_topic in posljednje_poruke:
            del posljednje_poruke[response_topic]

    resetuj_tajmer(response_topic)
    naredba = {"komanda": "zahtjev_navigacija", "zahtjeva": zahtjeva}
    mqtt_client.publish(topic, json.dumps(naredba))
    return f"Zahtjev za {zahtjeva} poslan."


@mcp.tool()
def ocitajStatuseVozila() -> str:
    """Vraca udaljenost od prepreke u cm i ugao rovera nakon poziva zahtjevajNavigacijskePodatke().
    Ako odgovor jos nije stigao, vraca status cekanja. Nakon 60 s vraca timeout.
    """
    if not mqtt_client.is_connected():
        return "Greska: MCP server nije povezan na MQTT broker."

    topic = "vucko/esp32/senzori"

    with brava:
        zapis = posljednje_poruke.get(topic)

    if zapis is None:
        je_timeout, poruka = provjeri_timeout(topic, timeout_sekundi=60)
        return poruka

    resetuj_tajmer(topic)

    if isinstance(zapis['payload'], dict):
        udaljenost = zapis['payload'].get('udaljenost', 'N/A')
        ugao = zapis['payload'].get('ugao', 'N/A')
    else:
        udaljenost = 'N/A'
        ugao = 'N/A'

    return f"Udaljenost: {udaljenost} cm, ugao: {ugao}"


@mcp.tool()
def ocitajMatricuProstora() -> str:
    """Vraca rezultate skeniranja pokrenutog sa posaljiKomanduMatrica().
    Skeniranje traje 30 do 120 s. Dok traje, funkcija vraca status cekanja,
    a nakon 120 s timeout.
    """
    if not mqtt_client.is_connected():
        return "Greska: MCP server nije povezan na MQTT broker."

    topic = "vucko/esp32/matrica"

    with brava:
        zapis = posljednje_poruke.get(topic)
    if zapis is None:
        je_timeout, _ = provjeri_timeout(topic, timeout_sekundi=120)

        if je_timeout:
            return "Timeout: skeniranje traje duze od 2 minute. Pokreni novo skeniranje sa posaljiKomanduMatrica()."
        else:
            vrijeme_z = zahtjev_tajmeri.get(topic)
            if vrijeme_z is None:
                vrijeme_z = time.time()
            sekundi_ostalo = 120 - int(time.time() - vrijeme_z)
            return f"Skeniranje u toku, preostalo {sekundi_ostalo} s."

    resetuj_tajmer(topic)
    return f"Rezultat skeniranja: {json.dumps(zapis['payload'])}"


@mcp.tool()
def posaljiKomanduVoznji(smjer: str, udaljenost_cm: int, izbjegavajPrepreke: bool) -> str:
    """Salje roveru komandu za voznju. Vraca potvrdu odmah, ne ceka da rover zavrsi voznju.

    smjer: "naprijed" ili "nazad"
    udaljenost_cm: udaljenost u cm
    izbjegavajPrepreke: ako je True, rover zaobilazi prepreke na putu
    """
    if not mqtt_client.is_connected():
        return "Greska: MCP server nije povezan na MQTT broker."

    topic = "vucko/esp32/komande"
    naredba = {
        "komanda": "vozi",
        "smjer": smjer,
        "udaljenost": udaljenost_cm,
        "izbjegavajPrepreke": izbjegavajPrepreke
    }
    mqtt_client.publish(topic, json.dumps(naredba))
    return f"Komanda za voznju poslana: {smjer} {udaljenost_cm} cm"


@mcp.tool()
def posaljiKomanduOkret(stepeni: int) -> str:
    """Okrece rover u mjestu za zadani ugao. Vraca potvrdu odmah, ne ceka kraj okreta.

    stepeni: pozitivne vrijednosti okrecu udesno, negativne ulijevo
    """
    if not mqtt_client.is_connected():
        return "Greska: MCP server nije povezan na MQTT broker."

    topic = "vucko/esp32/komande"
    naredba = {
        "komanda": "okreni",
        "stepeni": stepeni
    }
    mqtt_client.publish(topic, json.dumps(naredba))
    return f"Komanda za okret poslana: {stepeni} stepeni"


@mcp.tool()
def posaljiKomanduStop() -> str:
    """Odmah zaustavlja motore rovera. Prekida i skeniranje prostora ako je u toku."""
    if not mqtt_client.is_connected():
        return "Greska: MCP server nije povezan na MQTT broker."

    topic = "vucko/esp32/komande"
    naredba = {"komanda": "stani"}
    mqtt_client.publish(topic, json.dumps(naredba))
    return "Komanda za zaustavljanje poslana."


@mcp.tool()
def posaljiKomanduMatrica(duzinaKocke: int, sirinaKocke: int, duzinaKoraka: int, izbjegavajPrepreke: bool) -> str:
    """Pokrece autonomno skeniranje: rover obilazi rub pravougaonika zadanih dimenzija
    i na svakom koraku mjeri temperaturu i vlagu. Rezultat se cita pozivom
    ocitajMatricuProstora(); skeniranje traje 30 do 120 s.

    duzinaKocke, sirinaKocke: dimenzije prostora u cm
    duzinaKoraka: razmak izmedju tacaka mjerenja u cm
    izbjegavajPrepreke: ako je True, rover zaobilazi prepreke
    """
    if not mqtt_client.is_connected():
        return "Greska: MCP server nije povezan na MQTT broker."

    response_topic = "vucko/esp32/matrica"
    topic = "vucko/esp32/komande"

    with brava:
        if response_topic in posljednje_poruke:
            del posljednje_poruke[response_topic]

    resetuj_tajmer(response_topic)

    naredba = {
        "komanda": "matrica",
        "duzinaKocke": duzinaKocke,
        "sirinaKocke": sirinaKocke,
        "duzinaKoraka": duzinaKoraka,
        "izbjegavajPrepreke": izbjegavajPrepreke
    }
    mqtt_client.publish(topic, json.dumps(naredba))
    return f"Skeniranje {duzinaKocke}x{sirinaKocke} cm pokrenuto."


@mcp.tool()
def izlistaj_aktivne_uredjaje() -> str:
    """Dijagnostika: prikazuje MQTT topike sa kojih su stigle poruke i koliko je stara
    zadnja poruka na svakom od njih.
    """
    if not mqtt_client.is_connected():
        return "Greska: MCP server nije povezan na MQTT broker."

    with brava:
        if not posljednje_poruke:
            return "Jos nije stigla nijedna poruka sa rovera."
        redovi = []
        sada = time.time()
        for topic, zapis in sorted(posljednje_poruke.items()):
            starost = int(sada - zapis["vrijeme"])
            redovi.append(f"  {topic}  (prije {starost}s)")
        return "Aktivni topici:\n" + "\n".join(redovi)


if __name__ == "__main__":
    mcp.run()
