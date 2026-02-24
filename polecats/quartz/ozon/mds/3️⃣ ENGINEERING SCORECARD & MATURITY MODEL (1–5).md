# **3️⃣ ENGINEERING SCORECARD & MATURITY MODEL (1–5)**

## **Как да го използваш**

* Всеки домейн \= една оценка (1–5)

* Оценката се дава **само при evidence**

* Ако са между две нива → закръгляш надолу

* В доклада винаги показваш **защо**

---

# **3.1 DELIVERY FLOW**

### **1️⃣ Chaotic**

**Сигнали:**

* Няма измерим lead time

* Release-и са “събитие”

* Чести hotfix-и

* Sprint ≠ shipped work

**Evidence:**

* PR-и висят дни/седмици

* Release calendar липсва

* EM-и не знаят кога ще ship-нат

---

### **3️⃣ Partially Stable**

**Сигнали:**

* Някакъв cadence

* Частична предвидимост

* Bottleneck-и в review / QA / merge

**Evidence:**

* Lead time варира силно

* Чести spill-over-и

* Release отлагания

---

### **5️⃣ Predictable**

**Сигнали:**

* Малки, чести release-и

* Ясен end-to-end flow

* Plan ≈ reality

**Evidence:**

* Lead time стабилен

* PR cycle time \< 1–2 дни

* Release без drama

---

## **Как защитаваш оценката**

“Оценката не е за хората, а за системата.  
 Тя е базирана на това, което виждаме да се случва, не на намерения.”

---

# **3.2 ARCHITECTURE & TECHNICAL HEALTH**

### **1️⃣ Fragile**

**Сигнали:**

* Tight coupling

* Fear-driven dev

* Няма ownership

**Evidence:**

* “Това го пипа само X”

* DB като integration слой

* Shared libraries без owner

---

### **3️⃣ Mixed**

**Сигнали:**

* Някои стабилни части

* Други рискови

* Частични boundaries

**Evidence:**

* Частични domain-и

* Арх диаграми остарели

* Release-и все още зависими

---

### **5️⃣ Scalable**

**Сигнали:**

* Ясни домейни

* Decoupled releases

* Архитектурни принципи

**Evidence:**

* Екипите ship-ват независимо

* Ownership по системи

* Малки, локални промени

---

## **Защита**

“Тук не говорим за перфектна архитектура, а за такава, която позволява екипите да работят независимо.”

---

# **3.3 TEAM TOPOLOGY & ORG MODEL**

### **1️⃣ Ad-hoc**

**Сигнали:**

* Екипи по хора

* Всеки пипа всичко

* Bottleneck личности

**Evidence:**

* Няма ясни boundaries

* Чести cross-team блокажи

* “Всички помагаме”

---

### **3️⃣ Transitional**

**Сигнали:**

* Частично domain-based

* Все още зависимости

**Evidence:**

* Ownership не е пълен

* Platform липсва или е overloaded

---

### **5️⃣ Intentional**

**Сигнали:**

* Stream-aligned teams

* Ясни интерфейси

* Platform support

**Evidence:**

* Малко cross-team coordination

* Екипите знаят за какво отговарят

---

## **Защита**

“Орг моделът трябва да намалява координацията, не да я увеличава.”

---

# **3.4 DECISION-MAKING & GOVERNANCE**

### **1️⃣ Chaotic**

**Сигнали:**

* Ad-hoc решения

* Всичко е “спешно”

* CTO bottleneck

**Evidence:**

* Няма ясен decision owner

* Решения в Slack

---

### **3️⃣ Inconsistent**

**Сигнали:**

* Някои решения ясни

* Други – не

**Evidence:**

* Design docs, но без процес

* Conflicting решения

---

### **5️⃣ Clear**

**Сигнали:**

* Ясен decision framework

* Delegation

* Escalation path

**Evidence:**

* RACI / ownership

* Решения без drama

---

## **Защита**

“Когато решенията са ясни, скоростта се увеличава.”

---

# **3.5 TECH DEBT & SUSTAINABILITY**

### **1️⃣ Invisible**

**Сигнали:**

* Само fire-fighting

* Няма видим дълг

**Evidence:**

* Няма backlog

* Regression-и

---

### **3️⃣ Tracked**

**Сигнали:**

* Известен, но рядко приоритетен

**Evidence:**

* Тех debt ticket-и, но не в плана

---

### **5️⃣ Managed**

**Сигнали:**

* Планиран

* Мерен

**Evidence:**

* Allocation %

* Debt KPI

---

# **3.6 FINAL SCORECARD (пример)**

| Domain | Score |
| ----- | ----- |
| Delivery Flow | 2 |
| Architecture | 3 |
| Team Topology | 2 |
| Decision-making | 2 |
| Tech Debt | 1 |

➡️ **Интерпретация:**  
 Delivery-то страда основно заради org \+ decision bottleneck-и, не защото хората “не работят добре”.

---

# **3.7 Как го презентираш на C-level**

1. Първо показваш **картината**

2. После **взаимовръзките**

3. Накрая **какво да се направи първо**

Никога не защитаваш оценка “его-в-его”.

