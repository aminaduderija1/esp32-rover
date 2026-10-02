from machine import Pin, PWM
import time
import dht
from mpu6050 import MPU6050
from umqtt.robust import MQTTClient
import json
import network
import ntptime

from config import (
    WIFI_SSID,
    WIFI_LOZINKA,
    MQTT_BROKER_ADRESA,
    MQTT_BROKER_PORT,
    MQTT_KORISNICKO_IME,
    MQTT_LOZINKA,
    MQTT_ID_KLIJENTA,
)

MQTT_TOPIK_DHT11 = "vucko/tasmota/dht11"
MQTT_TOPIK_SENZORI = "vucko/esp32/senzori"
MQTT_TOPIK_KOMANDE = "vucko/esp32/komande"
MQTT_TOPIK_MATRICA = "vucko/esp32/matrica"

motorUlaz1 = Pin(27, Pin.OUT)
motorUlaz2 = Pin(26, Pin.OUT)
motorUlaz3 = Pin(25, Pin.OUT)
motorUlaz4 = Pin(33, Pin.OUT)

pwmMotorA = PWM(Pin(14), freq=1000)
pwmMotorB = PWM(Pin(32), freq=1000)

pwmServo = PWM(Pin(15), freq=50)
pinUkljucnica = Pin(12, Pin.OUT)
pinEho = Pin(13, Pin.IN)

dhtSenzor = dht.DHT11(Pin(4))
mpuSenzor = MPU6050()

klijentMQTT = None

PERIOD_UZORKOVANJA = 0.02
FAKTOR_Z_OSE = 1.25
BRZINA_ROVERA_CMS = 57.5

SERVO_PRAVO = 115
SERVO_POGLED_DESNO = 50
SERVO_POGLED_LIJEVO = 180

UDALJENOST_DETEKCIJE_PREPREKE = 15.0
UDALJENOST_SIGURNA = 20.0
UDALJENOST_SIGURNA_BOCNO = 25.0


class StanjeRovera:
    def __init__(self):
        self.trenutniUgao = 0.0
        self.zadnjaTemperatura = None
        self.zadnjaVlaga = None
        self.zadnjaUdaljenost = 0.0
        self.aktivnaKomanda = False
        self.tip_dht_zahtjeva = None
        self.vrijeme_zadnjeg_dht_ocitavanja = 0
        self.treba_stati=False
stanje = StanjeRovera()

PROFILI_PODEŠAVANJA = {
    "Fakultet": {

        "naziv": "Fakultet",
        "PWM_BRZINA_NAPRIJED": 750,
        "PWM_BRZINA_OKRET": 675,
        "ODSTUPANJE_MOTORA_B": 130,
        "PID_Kp": 95.0,
        "PID_Ki": 0.06,
        "PID_Kd": 2.5,
        "PWM_MIN": 400,
        "PWM_KOCENJE": 850,
    }
}

aktivniProfil = PROFILI_PODEŠAVANJA["Fakultet"]
odstupanjeZiroZ = None


def uspostavi_wifi_konekciju():
    wifi = network.WLAN(network.STA_IF)
    wifi.active(False)
    time.sleep_ms(200)
    wifi.active(True)
    time.sleep_ms(200)

    print(f"Povezujem na WiFi: {WIFI_SSID}...")
    wifi.connect(WIFI_SSID, WIFI_LOZINKA)

    timeout = 10
    while not wifi.isconnected() and timeout > 0:
        time.sleep(1)
        timeout -= 1
        print(f"  Čekam ({timeout}s)...")

    if wifi.isconnected():
        ip_adresa = wifi.ifconfig()[0]
        print(f"WiFi konekcija uspješna!")
        print(f"  IP adresa: {ip_adresa}")
        return True
    else:
        print(f"WiFi konekcija neuspješna")
        return False


def sinhronizuj_vrijeme():
    try:
        print("Sinhronizacija NTP vremena...")
        ntptime.settime()
        print("Vrijeme uspješno sinhronizovano.")
    except Exception as greska:
        print(f"NTP greška: {greska}")


def dobavi_tacan_datum_i_vrijeme():
    vrijeme_sekunde = time.time() + 7200
    godina, mjesec, dan, sat, minut, sekunda, _, _ = time.localtime(vrijeme_sekunde)
    return f"{sat:02d}:{minut:02d} {dan}.{mjesec}.{godina}."


def uspostavi_mqtt_konekciju():
    global klijentMQTT
    try:
        if klijentMQTT is not None:
            try:
                klijentMQTT.disconnect()
            except:
                pass

        klijentMQTT = MQTTClient(
            MQTT_ID_KLIJENTA,
            MQTT_BROKER_ADRESA,
            port=MQTT_BROKER_PORT,
            user=MQTT_KORISNICKO_IME,
            password=MQTT_LOZINKA,
            keepalive=60
        )
        klijentMQTT.set_callback(obrada_poruke)
        klijentMQTT.connect()
        klijentMQTT.subscribe(MQTT_TOPIK_KOMANDE)
        print(f"MQTT konekcija uspješna: {MQTT_BROKER_ADRESA}:{MQTT_BROKER_PORT}")
        return True
    except Exception as greska:
        print(f"MQTT greška: {greska}")
        klijentMQTT = None
        return False


def obrada_poruke(topik, poruka):
    try:
        topik_str = topik.decode('utf-8')
        poruka_str = poruka.decode('utf-8')
        print(f"Primljena poruka na {topik_str}: {poruka_str}")

        if topik_str == MQTT_TOPIK_KOMANDE:
            izvrsi_komandu(poruka_str)
    except Exception as greska:
        print(f"Greška pri obradi poruke: {greska}")


def izvrsi_komandu(json_poruka):
    print(f"DEBUG: Primio sam sirovu poruku: {json_poruka}")
    global stanje, aktivniProfil
    try:
        komanda = json.loads(json_poruka)
        tip = komanda.get("komanda")
        print(f"Komanda: {tip}")

        if tip == "vozi":
            try:
                udaljenost = int(komanda.get("udaljenost", 0))
                smjer = komanda.get("smjer", "naprijed")
                izbjegavaj = komanda.get("izbjegavajPrepreke", True)

                if smjer == "nazad":
                    print(f"  Vozi nazad {udaljenost}cm")
                    stanje.trenutniUgao = vozi_nazad(udaljenost, stanje.trenutniUgao, aktivniProfil)
                else:
                    print(f"  Vozi naprijed {udaljenost}cm")
                    stanje.trenutniUgao = vozi_naprijed(udaljenost, stanje.trenutniUgao, aktivniProfil, izbjegavaj)

                print(f"  Komanda završena. Trenutni ugao: {stanje.trenutniUgao:.2f}°")
            except Exception as greska:
                print(f"  Greška pri kretanju: {greska}")
                zaustavi()

        elif tip == "okreni":
            stepeni = int(komanda.get("stepeni", 0))
            print(f"  Okreni se {stepeni}°")
            stanje.trenutniUgao = skreni(stepeni, stanje.trenutniUgao, aktivniProfil)

        elif tip == "servo":
            stepeni = int(komanda.get("stepeni", SERVO_PRAVO))
            print(f"  Servo na {stepeni}°")
            postavi_servo_ugao(stepeni)

        elif tip == "stani":
            print(f"  Zaustavljam rovera")
            stanje.treba_stati=True
            zaustavi()

        elif tip == "matrica":
            duzina = int(komanda.get("duzinaKocke", 100))
            sirina = int(komanda.get("sirinaKocke", 100))
            korak = int(komanda.get("duzinaKoraka", 20))
            izbjegavaj = komanda.get("izbjegavajPrepreke", True)
            print(f"  Matrica: {duzina}x{sirina}cm, korak {korak}cm")
            rezultat = kreiraj_matricu_sa_skeniranjem(duzina, sirina, korak, izbjegavaj)
            objavi_matricu(rezultat, duzina, sirina, korak)

        elif tip == "zahtjev_dht":
            zahtjev = komanda.get("zahtjeva", "oboje")
            obradi_zahtjev_dht(zahtjev)

        elif tip == "zahtjev_navigacija":
            zahtjev = komanda.get("zahtjeva", "oboje")
            obradi_zahtjev_navigacija(zahtjev)

    except Exception as greska:
        print(f"Greška pri izvršavanju komande: {greska}")


def objavi_poruku(topik, poruka):
    try:
        if klijentMQTT is not None:
            if isinstance(poruka, dict):
                poruka["vrijeme_slanja"] = dobavi_tacan_datum_i_vrijeme()
                poruka = json.dumps(poruka)
            klijentMQTT.publish(topik, str(poruka))
    except Exception as greska:
        print(f"Greška pri objavljivanju: {greska}")


def procitaj_mqtt_poruke():
    global klijentMQTT
    try:
        if klijentMQTT is not None:
            klijentMQTT.check_msg()
    except Exception as greska:
        print(f"MQTT greška: {greska}")
        try:
            klijentMQTT.disconnect()
        except:
            pass
        time.sleep(2)
        uspostavi_mqtt_konekciju()


def postavi_servo_ugao(ugao):
    sirinaImpulsa = int(((ugao * 9.5) / 180) + 2.5)
    duznostEsp = int((sirinaImpulsa / 100) * 1023)
    pwmServo.duty(duznostEsp)
    time.sleep_ms(300)


def izmjeri_udaljenost():
    try:
        pinUkljucnica.value(0)
        time.sleep_us(2)
        pinUkljucnica.value(1)
        time.sleep_us(10)
        pinUkljucnica.value(0)

        vremenskoPrekoracenje = 20000
        vrijemePocetak = time.ticks_us()

        while pinEho.value() == 0:
            if time.ticks_diff(time.ticks_us(), vrijemePocetak) > vremenskoPrekoracenje:
                return 400.0

        vrijemePocetkaImpulsa = time.ticks_us()

        while pinEho.value() == 1:
            if time.ticks_diff(time.ticks_us(), vrijemePocetkaImpulsa) > vremenskoPrekoracenje:
                return 400.0

        vrijemeKrajaImpulsa = time.ticks_us()

        trajanjeImpulsa = time.ticks_diff(vrijemeKrajaImpulsa, vrijemePocetkaImpulsa)
        udaljenostCm = (trajanjeImpulsa * 0.0343) / 2
        return udaljenostCm
    except Exception:
        return 400.0


def ocitaj_okolinu():
    global stanje
    try:
        dhtSenzor.measure()
        temperatura=dhtSenzor.temperature()
        vlaga=dhtSenzor.humidity()
        stanje.vrijeme_zadnjeg_dht_ocitavanja = time.ticks_ms()
        return temperatura,vlaga
    except Exception as greska:
        return None,None


def kalibriraj_ziroskop(brojUzoraka=300):
    time.sleep_ms(500)
    odstupanjeZ = 0.0
    validniUzorci = 0
    while validniUzorci < brojUzoraka:
        try:
            odstupanjeZ += mpuSenzor.read_gyro_data()["z"]
            validniUzorci += 1
        except: pass
        time.sleep_ms(5)
    return odstupanjeZ / brojUzoraka


def ocitaj_ziro_z():
    try:
        return mpuSenzor.read_gyro_data()["z"] - odstupanjeZiroZ
    except:
        return 0.0


def obradi_zahtjev_dht(zahtjev):
    global stanje
    stanje.tip_dht_zahtjeva = zahtjev
    print(f"Postavljena zastavica za DHT11 očitavanje: {zahtjev}")


def izvrsi_dht_ocitavanje_iz_glavne_petlje():
    global stanje
    zahtjev = stanje.tip_dht_zahtjeva
    stanje.tip_dht_zahtjeva = None

    temperatura, vlaga = ocitaj_okolinu()

    if temperatura is not None and vlaga is not None:
        stanje.zadnjaTemperatura = temperatura
        stanje.zadnjaVlaga = vlaga
    else:
        print("Korištenje posljednjih poznatih DHT11 vrijednosti iz memorije.")
        temperatura = stanje.zadnjaTemperatura
        vlaga = stanje.zadnjaVlaga

    if temperatura is None or vlaga is None:
        print("Neuspješno očitavanje i nema historijskih podataka. Šaljem grešku.")
        objavi_poruku(MQTT_TOPIK_DHT11, {"greska": "Senzor trenutno nedostupan"})
        return

    podaci = {}
    if zahtjev in ["temperatura", "oboje"]:
        podaci["temperatura"] = int(temperatura)
    if zahtjev in ["vlaga", "oboje"]:
        podaci["vlaga"] = int(vlaga)

    if podaci:
        objavi_poruku(MQTT_TOPIK_DHT11, podaci)
        print("DHT11 podaci uspješno poslani.")


def obradi_zahtjev_navigacija(zahtjev):
    global stanje
    podaci = {}

    if zahtjev in ["udaljenost", "oboje"]:
        udaljenost = izmjeri_udaljenost()
        stanje.zadnjaUdaljenost = udaljenost
        podaci["udaljenost"] = round(udaljenost, 2)

    if zahtjev in ["ugao", "oboje"]:
        podaci["ugao"] = round(stanje.trenutniUgao, 2)

    if podaci:
        objavi_poruku(MQTT_TOPIK_SENZORI, podaci)


def postavi_smjer_motora(smjer):
    if smjer == "naprijed":
        motorUlaz1.value(1); motorUlaz2.value(0)
        motorUlaz3.value(1); motorUlaz4.value(0)
    elif smjer == "nazad":
        motorUlaz1.value(0); motorUlaz2.value(1)
        motorUlaz3.value(0); motorUlaz4.value(1)
    elif smjer == "lijevo":
        motorUlaz1.value(0); motorUlaz2.value(1)
        motorUlaz3.value(1); motorUlaz4.value(0)
    elif smjer == "desno":
        motorUlaz1.value(1); motorUlaz2.value(0)
        motorUlaz3.value(0); motorUlaz4.value(1)
    elif smjer == "stop":
        motorUlaz1.value(0); motorUlaz2.value(0)
        motorUlaz3.value(0); motorUlaz4.value(0)


def postavi_brzinu_motora(brzinaA, brzinaB):
    pwmMotorA.duty(int(brzinaA))
    pwmMotorB.duty(int(brzinaB))


def zaustavi():
    postavi_smjer_motora("stop")
    postavi_brzinu_motora(0, 0)


def koci(podešavanje):
    postavi_smjer_motora("stop")
    pwmMotorA.duty(podešavanje["PWM_KOCENJE"])
    pwmMotorB.duty(podešavanje["PWM_KOCENJE"])
    time.sleep_ms(50)
    zaustavi()


def ocuva_frekvenciju_petlje(vrijemePocetkaPetlje):
    vrijemeIzvrsenja = time.ticks_diff(time.ticks_ms(), vrijemePocetkaPetlje)
    vrijemeSpavanja = int((PERIOD_UZORKOVANJA * 1000) - vrijemeIzvrsenja)
    if vrijemeSpavanja > 0:
        time.sleep_ms(vrijemeSpavanja)


def vozi_naprijed_sa_mjerenjem(duzinaCm,korakCm, pocetniUgao, podešavanje, izbjegavanjeAktivno=True):
    if duzinaCm < 0:
        return []

    postavi_smjer_motora("naprijed")
    postavi_brzinu_motora(podešavanje["PWM_BRZINA_NAPRIJED"], podešavanje["PWM_BRZINA_NAPRIJED"])
    time.sleep_ms(100)

    trenutniUgao = pocetniUgao
    ciljaniUgao = pocetniUgao

    Kp = podešavanje["PID_Kp"]
    Ki = podešavanje["PID_Ki"]
    Kd = podešavanje["PID_Kd"]

    integralGreske = 0.0
    prethodnaGreska = 0.0

    trajanjeSekundi = duzinaCm / BRZINA_ROVERA_CMS
    ukupnoKrugova = int((trajanjeSekundi * 1000) / (PERIOD_UZORKOVANJA * 1000))

    MjerenjeKrugovi=int(ukupnoKrugova*(korakCm/duzinaCm))
    TrenutniKrug=0

    Mjerenja=[]

    for korak in range(ukupnoKrugova):
        vrijemePocetkaPetlje = time.ticks_ms()
        procitaj_mqtt_poruke()

        if izbjegavanjeAktivno and (korak % 3 == 0):
            if izmjeri_udaljenost() < UDALJENOST_DETEKCIJE_PREPREKE:
                trenutniUgao = zaobidji_prepreku(trenutniUgao, podešavanje)
                ciljaniUgao = pocetniUgao
                postavi_smjer_motora("naprijed")
                postavi_brzinu_motora(podešavanje["PWM_BRZINA_NAPRIJED"], podešavanje["PWM_BRZINA_NAPRIJED"])

        ziroZ = ocitaj_ziro_z()
        trenutniUgao += ziroZ * PERIOD_UZORKOVANJA

        greska = ciljaniUgao - trenutniUgao
        integralGreske = max(-40.0, min(40.0, integralGreske + greska * PERIOD_UZORKOVANJA))
        derivacijaGreske = (greska - prethodnaGreska) / PERIOD_UZORKOVANJA

        korekcija = Kp * greska + Ki * integralGreske + Kd * derivacijaGreske
        prethodnaGreska = greska

        brzinaLijeva = max(podešavanje["PWM_MIN"], min(1023, podešavanje["PWM_BRZINA_NAPRIJED"] - korekcija))
        brzinaDesna = max(podešavanje["PWM_MIN"], min(1023, podešavanje["PWM_BRZINA_NAPRIJED"] + korekcija))

        brzinaLijeva = brzinaLijeva + podešavanje["ODSTUPANJE_MOTORA_B"]
        brzinaLijeva = max(podešavanje["PWM_MIN"], min(1023, brzinaLijeva))

        postavi_brzinu_motora(brzinaDesna, brzinaLijeva)

        TrenutniKrug+=1

        if TrenutniKrug==MjerenjeKrugovi:
            print(f"Trenutni krug: {TrenutniKrug} ; Mjerim...")
            temperatura, vlaga = ocitaj_okolinu()

            Mjerenja.append({
                "Temperatura": temperatura,
                "Vlaga": vlaga
            })
            TrenutniKrug=0
        ocuva_frekvenciju_petlje(vrijemePocetkaPetlje)
    if len(Mjerenja) == int(duzinaCm/korakCm)-1:
        temperatura, vlaga = ocitaj_okolinu()

        Mjerenja.append({
            "Temperatura": temperatura,
            "Vlaga": vlaga
        })
    koci(podešavanje)
    return Mjerenja


def vozi_naprijed(duzinaCm, pocetniUgao, podešavanje, izbjegavanjeAktivno=True):
    if duzinaCm < 0:
        return vozi_nazad(abs(duzinaCm), pocetniUgao, podešavanje)

    postavi_smjer_motora("naprijed")
    postavi_brzinu_motora(podešavanje["PWM_BRZINA_NAPRIJED"], podešavanje["PWM_BRZINA_NAPRIJED"])
    time.sleep_ms(100)

    trenutniUgao = pocetniUgao
    ciljaniUgao = pocetniUgao

    Kp = podešavanje["PID_Kp"]
    Ki = podešavanje["PID_Ki"]
    Kd = podešavanje["PID_Kd"]

    integralGreske = 0.0
    prethodnaGreska = 0.0

    trajanjeSekundi = duzinaCm / BRZINA_ROVERA_CMS
    ukupnoKrugova = int((trajanjeSekundi * 1000) / (PERIOD_UZORKOVANJA * 1000))

    for korak in range(ukupnoKrugova):
        vrijemePocetkaPetlje = time.ticks_ms()
        procitaj_mqtt_poruke()

        if izbjegavanjeAktivno and (korak % 3 == 0):
            if izmjeri_udaljenost() < UDALJENOST_DETEKCIJE_PREPREKE:
                trenutniUgao = zaobidji_prepreku(trenutniUgao, podešavanje)
                ciljaniUgao = pocetniUgao
                postavi_smjer_motora("naprijed")
                postavi_brzinu_motora(podešavanje["PWM_BRZINA_NAPRIJED"], podešavanje["PWM_BRZINA_NAPRIJED"])

        ziroZ = ocitaj_ziro_z()
        trenutniUgao += ziroZ * PERIOD_UZORKOVANJA

        greska = ciljaniUgao - trenutniUgao
        integralGreske = max(-40.0, min(40.0, integralGreske + greska * PERIOD_UZORKOVANJA))
        derivacijaGreske = (greska - prethodnaGreska) / PERIOD_UZORKOVANJA

        korekcija = Kp * greska + Ki * integralGreske + Kd * derivacijaGreske
        prethodnaGreska = greska

        brzinaLijeva = max(podešavanje["PWM_MIN"], min(1023, podešavanje["PWM_BRZINA_NAPRIJED"] - korekcija))
        brzinaDesna = max(podešavanje["PWM_MIN"], min(1023, podešavanje["PWM_BRZINA_NAPRIJED"] + korekcija))

        brzinaLijeva = brzinaLijeva + podešavanje["ODSTUPANJE_MOTORA_B"]
        brzinaLijeva = max(podešavanje["PWM_MIN"], min(1023, brzinaLijeva))

        postavi_brzinu_motora(brzinaDesna, brzinaLijeva)
        ocuva_frekvenciju_petlje(vrijemePocetkaPetlje)

    koci(podešavanje)
    return trenutniUgao


def vozi_nazad(duzinaCm, pocetniUgao, podešavanje):
    postavi_smjer_motora("nazad")
    postavi_brzinu_motora(podešavanje["PWM_BRZINA_NAPRIJED"], podešavanje["PWM_BRZINA_NAPRIJED"])
    time.sleep_ms(100)

    trenutniUgao = pocetniUgao
    ciljaniUgao = pocetniUgao

    Kp = podešavanje["PID_Kp"]
    Ki = podešavanje["PID_Ki"]
    Kd = podešavanje["PID_Kd"]

    integralGreske = 0.0
    prethodnaGreska = 0.0

    trajanjeSekundi = duzinaCm / BRZINA_ROVERA_CMS
    ukupnoKrugova = int((trajanjeSekundi * 1000) / (PERIOD_UZORKOVANJA * 1000))

    for korak in range(ukupnoKrugova):
        vrijemePocetkaPetlje = time.ticks_ms()
        procitaj_mqtt_poruke()

        ziroZ = ocitaj_ziro_z()
        trenutniUgao += ziroZ * PERIOD_UZORKOVANJA

        greska = ciljaniUgao - trenutniUgao
        integralGreske = max(-40.0, min(40.0, integralGreske + greska * PERIOD_UZORKOVANJA))
        derivacijaGreske = (greska - prethodnaGreska) / PERIOD_UZORKOVANJA

        korekcija = Kp * greska + Ki * integralGreske + Kd * derivacijaGreske
        prethodnaGreska = greska

        brzinaLijeva = max(podešavanje["PWM_MIN"], min(1023, podešavanje["PWM_BRZINA_NAPRIJED"] + korekcija))
        brzinaDesna = max(podešavanje["PWM_MIN"], min(1023, podešavanje["PWM_BRZINA_NAPRIJED"] - korekcija))

        brzinaLijeva = brzinaLijeva + podešavanje["ODSTUPANJE_MOTORA_B"]
        brzinaLijeva = max(podešavanje["PWM_MIN"], min(1023, brzinaLijeva))

        postavi_brzinu_motora(brzinaDesna, brzinaLijeva)
        ocuva_frekvenciju_petlje(vrijemePocetkaPetlje)

    koci(podešavanje)
    return trenutniUgao


def skreni(okretZaStepeni, globalniUgaoPocetak, podešavanje, maksimalnoVrijemeSek=4):
    optimizovaniOkret = (okretZaStepeni + 180) % 360 - 180
    globalniCiljaniUgao = globalniUgaoPocetak + optimizovaniOkret

    if optimizovaniOkret > 0:
        postavi_smjer_motora("desno")
    else:
        postavi_smjer_motora("lijevo")

    postavi_brzinu_motora(podešavanje["PWM_BRZINA_OKRET"], podešavanje["PWM_BRZINA_OKRET"])
    time.sleep_ms(60)

    trenutniUgao = globalniUgaoPocetak
    ukupnoKrugova = int((maksimalnoVrijemeSek * 1000) / (PERIOD_UZORKOVANJA * 1000))

    for korak in range(ukupnoKrugova):
        vrijemePocetkaPetlje = time.ticks_ms()
        procitaj_mqtt_poruke()

        ziroZ = ocitaj_ziro_z() * FAKTOR_Z_OSE
        trenutniUgao += ziroZ * PERIOD_UZORKOVANJA

        deltaUgao = globalniCiljaniUgao - trenutniUgao - 8

        if abs(deltaUgao) < 2.5:
            break
        if optimizovaniOkret > 0 and deltaUgao < -4.0:
            break
        if optimizovaniOkret < 0 and deltaUgao > 4.0:
            break

        trenutnaBrzinaOkreta = (podešavanje["PWM_BRZINA_OKRET"]
                               if abs(deltaUgao) > 12
                               else max(290, int(podešavanje["PWM_BRZINA_OKRET"] * 0.75)))

        postavi_brzinu_motora(trenutnaBrzinaOkreta, trenutnaBrzinaOkreta)
        ocuva_frekvenciju_petlje(vrijemePocetkaPetlje)

    if optimizovaniOkret > 0:
        postavi_smjer_motora("lijevo")
    else:
        postavi_smjer_motora("desno")

    postavi_brzinu_motora(600, 600)
    time.sleep_ms(45)
    zaustavi()

    return trenutniUgao


def provjeri_prepreku(smjer):
    if smjer == "lijevo":
        postavi_servo_ugao(SERVO_POGLED_LIJEVO)
    elif smjer == "desno":
        postavi_servo_ugao(SERVO_POGLED_DESNO)
    else:
        postavi_servo_ugao(SERVO_PRAVO)

    udaljenost = izmjeri_udaljenost()
    return udaljenost > UDALJENOST_SIGURNA


def zaobidji_prepreku(trenutniUgao, podešavanje):
    zaustavi()

    desnoSlobodno = provjeri_prepreku("desno")
    lijevoSlobodno = provjeri_prepreku("lijevo")
    postavi_servo_ugao(SERVO_PRAVO)

    if desnoSlobodno:
        okretSmjer = 270
        okretPovratak = 90
        servoSmjer = SERVO_POGLED_LIJEVO
    elif lijevoSlobodno:
        okretSmjer = 90
        okretPovratak = 270
        servoSmjer = SERVO_POGLED_DESNO
    else:
        okretSmjer = 270
        okretPovratak = 90
        servoSmjer = SERVO_POGLED_LIJEVO

    trenutniUgao = skreni(okretSmjer, trenutniUgao, podešavanje)
    postavi_servo_ugao(servoSmjer)
    time.sleep_ms(200)

    vrijemePocetkaManevra = time.ticks_ms()
    postavi_smjer_motora("naprijed")
    postavi_brzinu_motora(podešavanje["PWM_BRZINA_NAPRIJED"], podešavanje["PWM_BRZINA_NAPRIJED"] + podešavanje["ODSTUPANJE_MOTORA_B"])

    while izmjeri_udaljenost() < UDALJENOST_SIGURNA_BOCNO:
        time.sleep_ms(50)

    time.sleep_ms(500)

    zaustavi()
    trajanjeBocnoMs = time.ticks_diff(time.ticks_ms(), vrijemePocetkaManevra)

    sekundiBocno = trajanjeBocnoMs / 1000.0
    duzinaBocnoCm = sekundiBocno * BRZINA_ROVERA_CMS

    trenutniUgao = skreni(okretPovratak, trenutniUgao, podešavanje)
    postavi_smjer_motora("naprijed")
    postavi_brzinu_motora(podešavanje["PWM_BRZINA_NAPRIJED"], podešavanje["PWM_BRZINA_NAPRIJED"] + podešavanje["ODSTUPANJE_MOTORA_B"])

    while izmjeri_udaljenost() < UDALJENOST_SIGURNA_BOCNO:
        time.sleep_ms(50)

    time.sleep_ms(500)

    zaustavi()
    trenutniUgao = skreni(okretPovratak, trenutniUgao, podešavanje)
    postavi_servo_ugao(SERVO_PRAVO)

    trenutniUgao = vozi_naprijed(duzinaBocnoCm, trenutniUgao, podešavanje, izbjegavanjeAktivno=False)
    trenutniUgao = skreni(okretSmjer, trenutniUgao, podešavanje)

    return trenutniUgao


def mapiraj_rubove(matrica_mjerenja):
    H = len(matrica_mjerenja[0])

    W = len(matrica_mjerenja[1])

    broj_redova = H + 1
    broj_kolona = W + 1

    prostorna_matrica = [['-' for _ in range(broj_kolona)] for _ in range(broj_redova)]

    for i in range(H):
        prostorna_matrica[H - 1 - i][0] = matrica_mjerenja[0][i]

    for i in range(W):
        prostorna_matrica[0][1 + i] = matrica_mjerenja[1][i]

    for i in range(H):
        prostorna_matrica[1 + i][W] = matrica_mjerenja[2][i]

    for i in range(W):
        prostorna_matrica[H][W - 1 - i] = matrica_mjerenja[3][i]

    return prostorna_matrica


def kreiraj_matricu_sa_skeniranjem(duzinaKocke, sirinaKocke, duzinaKoraka, izbjegavajPrepreke):
    global stanje

    matrica = []
    broj_redaka = int(duzinaKocke / duzinaKoraka)
    broj_kolona = int(sirinaKocke / duzinaKoraka)

    print(f"Kreiranje matrice: {broj_redaka} redaka x {broj_kolona} kolona")

    stanje.trenutniUgao = 0.0
    postavi_servo_ugao(SERVO_PRAVO)
    time.sleep(1)

    PoKoloniIliRedu=1

    Mjerenja=[]

    for i in range(1,5):
        print(f"{i}. krug")
        if PoKoloniIliRedu==1:
            Mjerenja = vozi_naprijed_sa_mjerenjem(duzinaKocke,duzinaKoraka,stanje.trenutniUgao, aktivniProfil, izbjegavajPrepreke)
            print(f"Izmjereni red u funkciji za matricu:  {Mjerenja}")
            if stanje.treba_stati is True:
                stanje.treba_stati=False
                return matrica

            stanje.trenutniUgao = skreni(270, stanje.trenutniUgao, aktivniProfil)
            PoKoloniIliRedu=2

            matrica.append(Mjerenja)
            continue
        elif PoKoloniIliRedu==2:
            Mjerenja = vozi_naprijed_sa_mjerenjem(sirinaKocke,duzinaKoraka,stanje.trenutniUgao, aktivniProfil, izbjegavajPrepreke)

            if stanje.treba_stati is True:
                stanje.treba_stati=False
                return matrica

            stanje.trenutniUgao = skreni(270, stanje.trenutniUgao, aktivniProfil)
            PoKoloniIliRedu=1

            matrica.append(Mjerenja)
            continue
    return mapiraj_rubove(matrica)


def objavi_matricu(matrica, duzinaKocke, sirinaKocke, duzinaKoraka):
    poruka = {
        "duzinaKocke": duzinaKocke,
        "sirinaKocke": sirinaKocke,
        "duzinaKoraka": duzinaKoraka,
        "MatricaProstora": matrica
    }
    objavi_poruku(MQTT_TOPIK_MATRICA, poruka)
    print(f"Matrica objavljena na {MQTT_TOPIK_MATRICA}")


def glavni_program(profil_podešavanja="asfalt"):
    global odstupanjeZiroZ, aktivniProfil, stanje

    if profil_podešavanja not in PROFILI_PODEŠAVANJA:
        print(f"Nepoznat profil: {profil_podešavanja}")
        return

    aktivniProfil = PROFILI_PODEŠAVANJA[profil_podešavanja]

    print("="*70)
    print(f"Inicijalizacija sa profilom: {aktivniProfil['naziv']}")
    print("="*70)

    if not uspostavi_wifi_konekciju():
        print("Nema WiFi konekcije - MQTT neće raditi")
        return

    sinhronizuj_vrijeme()

    if not uspostavi_mqtt_konekciju():
        print("MQTT nije dostupan")

    odstupanjeZiroZ = kalibriraj_ziroskop()
    print(f"Kalibriran offset žiroskopa: {odstupanjeZiroZ:.4f}")

    try:
        postavi_servo_ugao(SERVO_PRAVO)
        time.sleep(1)

        print("\nRover je spreman - čeka komande na MQTT")
        print(f"Slušam na topiku: {MQTT_TOPIK_KOMANDE}\n")

        vrijeme_zadnje_provere_mqtt = time.ticks_ms()

        while True:
            vrijeme_pocetak = time.ticks_ms()

            try:
                procitaj_mqtt_poruke()

                if stanje.tip_dht_zahtjeva is not None:
                    izvrsi_dht_ocitavanje_iz_glavne_petlje()

                if time.ticks_diff(vrijeme_pocetak, vrijeme_zadnje_provere_mqtt) >= 5000:
                    if klijentMQTT is not None:
                        try:
                            klijentMQTT.ping()
                        except:
                            print("MQTT konekcija prekinuta - pokušavam reconnect...")
                            uspostavi_mqtt_konekciju()

                    vrijeme_zadnje_provere_mqtt = vrijeme_pocetak

                time.sleep_ms(10)

            except Exception as greska:
                print(f"Greška u glavnoj petlji: {greska}")
                time.sleep_ms(100)

    except KeyboardInterrupt:
        print("\nPrekinuto korisničkom akcijom")
        zaustavi()
    except Exception as greska:
        print(f"Greška: {greska}")
        zaustavi()
    finally:
        if klijentMQTT is not None:
            try:
                klijentMQTT.disconnect()
                print("MQTT konekcija zatvorena")
            except:
                pass


if __name__ == "__main__":
    glavni_program("Fakultet")
