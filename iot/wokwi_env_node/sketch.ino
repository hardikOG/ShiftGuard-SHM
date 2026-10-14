// OPTIONAL: Wokwi ESP32 + DHT22 virtual temperature node for ShiftGuard.
// Publishes {"temp": x} every 2 s to shm/<WOKWI_ID>/env/override on a public broker.
// iot/wokwi_relay.py forwards ONLY this topic into the local pipeline, so the bridge's sensor data
// never leaves your machine. Turn the DHT22's temperature slider in Wokwi to create a live cold snap.
//
//   1. Change WOKWI_ID below to something unique (e.g. "sg-" + your initials + 4 digits).
//   2. python run_demo.py --wokwi-id <the same id>
// Libraries (Wokwi "Library Manager"): PubSubClient, DHT sensor library
// The green LED blinks on every publish; the red LED is on while MQTT is disconnected.
#include <WiFi.h>
#include <PubSubClient.h>
#include <DHT.h>

const char* WOKWI_ID  = "sg-change-me";
const char* WIFI_SSID = "Wokwi-GUEST";
const char* WIFI_PASS = "";
const char* MQTT_HOST = "broker.hivemq.com";
const int   MQTT_PORT = 1883;
const int   PIN_DHT = 15, PIN_LED_OK = 2, PIN_LED_ERR = 4;

DHT dht(PIN_DHT, DHT22);
WiFiClient net;
PubSubClient mqtt(net);
char topicBuf[64];

void connectAll() {
  digitalWrite(PIN_LED_ERR, HIGH);
  while (WiFi.status() != WL_CONNECTED) { delay(200); }
  while (!mqtt.connected()) {
    String id = "shm-env-" + String((uint32_t)esp_random(), HEX);
    if (!mqtt.connect(id.c_str())) {
      Serial.print("MQTT connect failed, state="); Serial.println(mqtt.state());
      delay(1000);
    }
  }
  digitalWrite(PIN_LED_ERR, LOW);
}

void setup() {
  Serial.begin(115200);
  pinMode(PIN_LED_OK, OUTPUT);
  pinMode(PIN_LED_ERR, OUTPUT);
  dht.begin();
  snprintf(topicBuf, sizeof(topicBuf), "shm/%s/env/override", WOKWI_ID);
  WiFi.begin(WIFI_SSID, WIFI_PASS, 6);
  mqtt.setServer(MQTT_HOST, MQTT_PORT);
  connectAll();
  Serial.print("ShiftGuard env node online, publishing to "); Serial.println(topicBuf);
}

void loop() {
  if (!mqtt.connected()) connectAll();
  mqtt.loop();
  float t = dht.readTemperature();
  if (!isnan(t)) {
    char buf[48];
    snprintf(buf, sizeof(buf), "{\"temp\":%.2f}", t);
    if (mqtt.publish(topicBuf, buf)) {
      digitalWrite(PIN_LED_OK, HIGH); delay(80); digitalWrite(PIN_LED_OK, LOW);
    }
    Serial.println(buf);
  }
  delay(2000);
}
