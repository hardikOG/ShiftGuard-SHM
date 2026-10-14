// OPTIONAL: Wokwi ESP32 + DHT22 virtual temperature node for ShiftGuard.
// Publishes {"temp": x} to shm/bridge01/env/override every 2 s. Turn the DHT22's
// temperature knob in Wokwi during the demo to create a live cold snap.
// Wokwi runs in the browser, so it can only reach a PUBLIC broker: start the demo with
//   python run_demo.py --broker broker.hivemq.com
// Libraries (Wokwi "Library Manager"): PubSubClient, DHT sensor library
#include <WiFi.h>
#include <PubSubClient.h>
#include <DHT.h>

const char* WIFI_SSID = "Wokwi-GUEST";
const char* WIFI_PASS = "";
const char* MQTT_HOST = "broker.hivemq.com";
const int   MQTT_PORT = 1883;
const char* TOPIC     = "shm/bridge01/env/override";

DHT dht(15, DHT22);
WiFiClient net;
PubSubClient mqtt(net);

void connectAll() {
  while (WiFi.status() != WL_CONNECTED) { delay(200); }
  while (!mqtt.connected()) {
    String id = "shm-env-" + String((uint32_t)esp_random(), HEX);
    if (!mqtt.connect(id.c_str())) delay(500);
  }
}

void setup() {
  Serial.begin(115200);
  dht.begin();
  WiFi.begin(WIFI_SSID, WIFI_PASS, 6);
  mqtt.setServer(MQTT_HOST, MQTT_PORT);
  connectAll();
  Serial.println("ShiftGuard env node online");
}

void loop() {
  if (!mqtt.connected()) connectAll();
  mqtt.loop();
  float t = dht.readTemperature();
  if (!isnan(t)) {
    char buf[48];
    snprintf(buf, sizeof(buf), "{\"temp\":%.2f}", t);
    mqtt.publish(TOPIC, buf);
    Serial.println(buf);
  }
  delay(2000);
}
