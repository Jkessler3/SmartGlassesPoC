#include <Arduino.h>

// ---------------------------
// Pinout
// ---------------------------
const int IR_PIN      = 4;  // GPIO1 -> MOSFET gate
const int REC_LED_PIN = 1;  // GPIO4 -> record LED
const int BUTTON_PIN  = 2;  // GPIO2 -> button -> GND (INPUT_PULLUP)
const bool REC_LED_ACTIVE_HIGH = true;  // Set true for GPIO -> resistor -> LED -> GND wiring.

// ---------------------------
// PWM
// ---------------------------
const int PWM_FREQ = 5000;
const int PWM_RES  = 8;   // 0..255

// ---------------------------
// State
// ---------------------------
bool rec = false;
bool ir_on = false;
uint8_t brightness = 255;
bool serial_host_seen = false;

// ---------------------------
// Debounce
// ---------------------------
bool lastBtn = HIGH;
unsigned long lastChange = 0;
const unsigned long DEBOUNCE_MS = 40;

// ---------------------------
// Outputs
// ---------------------------
void setRecLed(bool on) {
  digitalWrite(REC_LED_PIN, on == REC_LED_ACTIVE_HIGH ? HIGH : LOW);
}

void blinkRecLed(int count, int delay_ms = 80) {
  for (int i = 0; i < count; ++i) {
    setRecLed(true);
    delay(delay_ms);
    setRecLed(false);
    delay(delay_ms);
  }
}

void applyOutputs() {
  setRecLed(rec);
  ledcWrite(IR_PIN, ir_on ? brightness : 0);
}

void printStatus() {
  Serial.println("ID=XIAO_REC_CTRL");
  Serial.print("REC="); Serial.println(rec ? 1 : 0);
  Serial.print("IR=");  Serial.println(ir_on ? 1 : 0);
  Serial.print("B=");   Serial.println((int)brightness);
  Serial.flush();
}

void setRec(bool on) {
  rec = on;

  // Recording ON forces IR on.
  // Recording OFF does NOT force IR off.
  // That lets the GUI IR button work independently.
  if (rec) ir_on = true;

  applyOutputs();

  Serial.print("REC="); Serial.println(rec ? 1 : 0);
  Serial.print("IR=");  Serial.println(ir_on ? 1 : 0);
  Serial.flush();
}

void setIr(bool on) {
  ir_on = on;
  applyOutputs();
  Serial.print("IR="); Serial.println(ir_on ? 1 : 0);
  Serial.flush();
}

void setBrightness(int b) {
  if (b < 0) b = 0;
  if (b > 255) b = 255;
  brightness = (uint8_t)b;
  applyOutputs();
  Serial.print("B="); Serial.println((int)brightness);
  Serial.flush();
}

void setup() {
  pinMode(REC_LED_PIN, OUTPUT);
  pinMode(BUTTON_PIN, INPUT_PULLUP);
  pinMode(IR_PIN, OUTPUT);

  Serial.begin(115200);
  delay(200);

  bool ok = ledcAttach(IR_PIN, PWM_FREQ, PWM_RES);
  if (!ok) Serial.println("WARN: ledcAttach failed");

  setRecLed(false);
  blinkRecLed(2);

  rec = false;
  ir_on = false;
  brightness = 255;
  applyOutputs();

  printStatus();
}

void loop() {
  bool serial_now = (bool)Serial;
  if (serial_now && !serial_host_seen) {
    delay(50);
    printStatus();
  }
  serial_host_seen = serial_now;

  // ---- Button toggle ----
  bool btn = digitalRead(BUTTON_PIN);

  if (btn != lastBtn) {
    lastChange = millis();
    lastBtn = btn;
  }

  if ((millis() - lastChange) > DEBOUNCE_MS) {
    static bool handled = false;

    if (btn == LOW && !handled) {
      handled = true;
      setRec(!rec);
    }

    if (btn == HIGH) {
      handled = false;
    }
  }

  // ---- Serial commands ----
  if (Serial.available()) {
    String cmd = Serial.readStringUntil('\n');
    cmd.trim();
    cmd.toUpperCase();

    if (cmd == "STATUS?" || cmd == "S") {
      printStatus();
    } else if (cmd == "ID?" || cmd == "ID") {
      Serial.println("ID=XIAO_REC_CTRL");
      Serial.flush();
    } else if (cmd.startsWith("REC=")) {
      setRec(cmd.endsWith("1"));
    } else if (cmd.startsWith("IR=")) {
      setIr(cmd.endsWith("1"));
    } else if (cmd.startsWith("B=")) {
      setBrightness(cmd.substring(2).toInt());
    } else if (cmd == "1") {
      setRec(true);
    } else if (cmd == "0") {
      setRec(false);
    }
  }

  delay(1);
}
