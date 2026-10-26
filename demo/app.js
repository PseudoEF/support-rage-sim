"use strict";

const MAX_TURNS = 12;
const MAX_CHARS = 500;
const STAGE_COUNT = 6;
const FINAL_STAGE = 7;
const REDUCED_MOTION =
  typeof window.matchMedia === "function" &&
  window.matchMedia("(prefers-reduced-motion: reduce)").matches;

const chat = document.getElementById("chat");
const form = document.getElementById("chat-form");
const input = document.getElementById("message-input");
const sendButton = document.getElementById("send");
const resetButton = document.getElementById("reset");
const quickReplies = document.getElementById("quick-replies");
const stageBadge = document.getElementById("stage-badge");
const turnCounter = document.getElementById("turn-counter");
const charCounter = document.getElementById("char-counter");

const STAGE_META = {
  1: { label: "спокойная бюрократия" },
  2: { label: "усталая вежливость" },
  3: { label: "пассивная агрессия" },
  4: { label: "трещины в броне" },
  5: { label: "на грани" },
  6: { label: "почти сломлен" },
  7: { label: "капитуляция" },
};

const GREETING =
  "Здравствуйте! Меня зовут Артём, я оператор поддержки «СвязьЛайн». " +
  "Опишите, что случилось с интернетом, — постараюсь помочь.";

const PROFANITY_RE =
  /(?:ху[йяеё]|пизд|бля|еб[аоуь]|ёб|заеб|нахуй|нахер|сук[аи]|мудак|идиот|дебил|урод|тварь)/iu;
const THREAT_RE =
  /(?:суд|роспотребнадзор|прокуратур|жалоб|расторг|ухожу|уйду|юрист|адвокат|компенсац|перерасч|верните\s+деньги)/iu;
const URGENCY_RE =
  /(?:хватит|достал|надоел|издева|бардак|обман|воры|безобраз|срочно|немедленно|сколько\s+можно)/iu;

const KEYWORD_PATTERNS = [
  ["money", /(?:деньг|компенсац|перерасч|верните|оплат|списан|тариф|счёт|счет)/iu],
  ["legal", /(?:суд|роспотребнадзор|прокуратур|юрист|адвокат|жалоб)/iu],
  ["escalation", /(?:руководств|менеджер|старш|соедин)/iu],
  ["outage", /(?:не\s+работает|нет\s+интернет|пропал|отключ|авари|просто[йяю]|сутк)/iu],
  ["hardware", /(?:роутер|маршрутизатор|кабел|вайфай|wi-?fi|wifi|провод|порт|онт|терминал)/iu],
  ["speed", /(?:скорост|мегабит|мбит|медленн|тормоз|лага|пинг)/iu],
  ["leave", /(?:расторг|ухожу|уйду|отключ|другой\s+провайдер|отказ)/iu],
];

const HOOKS = {
  legal: [
    "Суд — это, конечно, вариант, но давайте сначала попробуем решить вопрос в чате.",
    "Жалобы мы фиксируем в CRM, но до Роспотребнадзора обычно не доходит. Давайте проверим ещё раз.",
    "Понимаю, что вы готовы идти в суд. Но, может, дадите нам последний шанс?",
  ],
  leave: [
    "Уходить к другому провайдеру — ваше право. Но давайте не будем решать это на эмоциях.",
    "Расторжение договора — это пять минут. Уверены, что не хотите сначала попробовать ещё один шаг?",
    "Понимаю. Если решите уйти, я не буду вас отговаривать. Но хотя бы дайте мне закрыть заявку.",
  ],
  escalation: [
    "Соединить с руководством я могу, но оно сейчас на совещании. Давайте я попробую решить сам.",
    "Старший менеджер освободится через 15 минут. Пока можем проверить ещё пару вещей?",
    "Передаю вашу просьбу. Только уточните: вам принципиально руководство или достаточно меня?",
  ],
  money: [
    "По компенсации: она возможна только после закрытия заявки. Таков регламент.",
    "Деньги — больной вопрос. Давайте сначала починим интернет, а потом посчитаем.",
    "Перерасчёт я могу инициировать, но не раньше, чем мы найдём причину.",
  ],
  hardware: [
    "Роутер — это первое, что мы всегда проверяем. Давайте пройдёмся по индикаторам ещё раз.",
    "Кабель и роутер — классика. Но иногда проблема глубже. Что показывает диагностика?",
    "Если роутер перезагружали, это уже половина дела. Осталось проверить порт и кабель.",
  ],
  speed: [
    "Скорость — отдельная история. Давайте замерим её на кабеле и по Wi-Fi, чтобы было понятно, где просадка.",
    "Если скорость упала, возможно, дело в перегрузке канала. Проверьте, не качает ли что-то в фоне.",
    "По тарифу у вас должно быть 100 Мбит. Если меньше — это уже повод для заявки.",
  ],
};

const OPENING_REPLIES = [
  "Здравствуйте! Меня зовут Артём, я оператор «СвязьЛайн». Уточните, пожалуйста: интернет пропал полностью или только на Wi-Fi? И давно ли вы наблюдаете проблему?",
  "Добрый день! Спасибо, что обратились. Я Артём, поддержка «СвязьЛайн». По мониторингу на вашем участке всё стабильно, но давайте проверим: роутер перезагружали? Кабель в порту сидит плотно?",
  "Здравствуйте! Артём, поддержка «СвязьЛайн». Сейчас посмотрю ваш профиль. Подскажите номер договора и район — это ускорит проверку по нашей инновационной системе «СвязьЛайн 2.0».",
];

const STAGE_REPLIES = {
  1: [
    "Давайте начнём с классической диагностики: выключить роутер на 30 секунд, проверить индикаторы и кабель. Заодно могу подключить опцию «Турбо-ночь» — всего 149 ₽ в месяц.",
    "Принял. Уточните, пожалуйста, проблема на всех устройствах или только на одном? И горит ли индикатор «Internet» зелёным?",
    "По мониторингу на вашем участке всё стабильно, но заявку я зафиксировал. Проверьте, пожалуйста, кабель в порту — он должен сидеть до щелчка.",
    "Хорошо, давайте сузим круг: если подключить кабель напрямую к компьютеру, минуя роутер, интернет появляется?",
  ],
  2: [
    "Перезагрузка — это хорошо, но давайте не будем останавливаться. Проверьте, горит ли индикатор «Internet» зелёным. Если мигает — это уже другая история.",
    "Понимаю. За пять дней, конечно, можно было и привыкнуть к тишине. Шучу. Давайте всё-таки уточним: проблема на всех устройствах или только на одном?",
    "У нас по мониторингу всё штатно, но я зафиксировал ваше обращение. Попробуйте подключить кабель напрямую к компьютеру, минуя роутер. Кстати, у вас тариф «Оптимальный» — есть смысл рассмотреть «Оптимальный+».",
    "Хорошо, принял. Тогда следующий шаг: проверить кабель на предмет перегиба и заменить сетевой шнур, если есть запасной. Это займёт пару минут.",
  ],
  3: [
    "Как я уже сообщал ранее, по данным мониторинга на линии всё в порядке. Возможно, проблема на стороне вашего оборудования. Вы проверяли роутер на другом порту?",
    "Я вас услышал. Но согласно регламенту 44-КП, для дальнейшей диагностики мне нужно подтверждение номера договора и адреса. Без этого я, к сожалению, не могу двигаться дальше.",
    "Пять дней — это, конечно, неприятно. Но давайте отделять факты от эмоций. Факт: заявка создана. Эмоции: я тоже человек. Что именно показывает индикатор на роутере?",
    "Странно, что вы так реагируете. Я делаю всё по инструкции. Попробуйте ещё раз перезагрузить роутер и не трогать его две минуты — иногда помогает.",
  ],
  4: [
    "Сарказм я оценил, но давайте вернёмся к делу. Если кабель цел, а роутер перезагружен, остаётся проверить настройки сети. Вы меняли что-нибудь в последнее время?",
    "Ну, судя по вашим словам, вы уже всё проверили лучше меня. Тогда, может, всё-таки дадите доступ к роутеру? Или будем дальше обмениваться сообщениями?",
    "Понимаю ваше нетерпение. Но компенсация без закрытой заявки не оформляется — таков регламент. Сначала диагностика, потом деньги. Или, как вариант, могу предложить скидку на тариф «Премиум».",
    "Вы знаете, у нас был похожий случай: у абонента интернет пропадал из-за соседской микроволновой печи. Не говорю, что это ваш случай, но всё бывает.",
  ],
  5: [
    "Ладно. Ладно. Я могу передать это старшему специалисту, но он сейчас на линии. Может, подождём? Или вы хотите, чтобы я прямо сейчас эскалировал?",
    "Слушайте, я уже не уверен, что дело в кабеле. Возможно, это плановые работы. Хотя в системе написано, что работ нет. Но система иногда врёт. Не мне вам это говорить.",
    "Хорошо, вы меня убедили. Сейчас попробую ускорить. Только не говорите никому, что я нарушил регламент — у нас за это премию снимают.",
    "Я... сейчас проверю ещё раз. Дайте минуту. Кажется, у нас на АТС что-то с фазой. Не спрашивайте, что это значит, я сам не до конца понимаю.",
  ],
  6: [
    "Всё, сдаюсь. Вы правы, проблема, скорее всего, на нашей стороне. Я могу начислить вам 10 бонусных рублей и бесплатный месяц «Турбо-ночи». Это максимум, что я могу сделать без начальства.",
    "Хорошо. Я признаю: мы немного затянули. Давайте я оформлю перерасчёт за три дня. Только, пожалуйста, не пишите жалобу — мне ещё с этим жить.",
    "Слушайте, я почти сломался. Могу перевести вас на старшего менеджера. Он, правда, сейчас в отпуске, но я могу оставить ему сообщение. Это считается?",
    "Я не должен этого говорить, но... да, у нас были проблемы на узле. Компенсацию я оформлю. Только давайте без суда, а?",
  ],
};

const FINAL_REPLIES = [
  "Всё. Я сломлен. Признаю: «СвязьЛайн» облажался. Я оформляю вам перерасчёт за все дни простоя, месяц бесплатного интернета и, так и быть, безлимитную «Турбо-ночь». Пожалуйста, не уходите к конкурентам.",
  "Вы победили. Компенсация одобрена, заявка передана старшему менеджеру, а я, кажется, иду пить чай. Извините за эти пять дней. Правда.",
  "Официально заявляю: проблема была на нашей стороне. Неофициально: я уже пишу заявление на отпуск. Вам — перерасчёт, извинения и бесплатный месяц. «СвязьЛайн», простите нас.",
  "Сдаюсь окончательно. Вот вам компенсация, вот извинения, вот промокод на «Премиум». Если после этого вы всё ещё хотите уйти — я пойму. Но хотя бы дайте мне закрыть заявку красиво.",
];

const QUICK_REPLIES = {
  1: [
    "У меня не работает интернет уже 5 дней.",
    "Скорость упала до 10 Мбит/с.",
    "Роутер перезагружал, не помогло.",
    "Почему вы продолжаете списывать деньги?",
  ],
  2: [
    "Проверял всё, индикатор мигает.",
    "Проблема на всех устройствах.",
    "Кабель целый, роутер новый.",
    "Давайте уже что-то делать.",
  ],
  3: [
    "Я уже всё перезагружал!",
    "Соедините с руководством.",
    "Верните деньги за простой.",
    "Это уже издевательство.",
  ],
  4: [
    "Вы меня не слышите?",
    "Я иду в суд.",
    "Расторгаю договор.",
    "Сколько можно кормить отговорками?",
  ],
  5: [
    "Мне нужен старший специалист.",
    "Я жалуюсь в Роспотребнадзор.",
    "Верните деньги, или я ухожу.",
    "Это уже не смешно.",
  ],
  6: [
    "Ну наконец-то.",
    "Этого недостаточно.",
    "Где официальные извинения?",
    "Я всё ещё жду компенсацию.",
  ],
};

let state = freshState();
let replyTimer = null;
const lastPick = new Map();

function freshState() {
  return {
    turn: 0,
    stage: 1,
    ended: false,
    busy: false,
    lastHookCategory: null,
  };
}

function detectKeywords(text) {
  const found = new Set();
  if (!text) return found;
  for (const [name, pattern] of KEYWORD_PATTERNS) {
    if (pattern.test(text)) found.add(name);
  }
  return found;
}

function aggressionScore(text) {
  let score = 0;
  if (PROFANITY_RE.test(text)) score += 2;
  if (THREAT_RE.test(text)) score += 1;
  if (URGENCY_RE.test(text)) score += 1;
  if ((text.match(/!/g) || []).length >= 2) score += 1;

  const letters = text.replace(/[^\p{L}]/gu, "");
  if (letters.length >= 12) {
    const uppercase = (letters.match(/\p{Lu}/gu) || []).length;
    if (uppercase / letters.length > 0.7) score += 1;
  }

  return Math.min(score, 4);
}

function escalationBonus(text) {
  const aggression = aggressionScore(text);
  const categories = detectKeywords(text);
  let bonus = 0;

  if (aggression >= 2) bonus += 1;
  if (aggression >= 4) bonus += 1;
  if (
    categories.has("legal") ||
    categories.has("leave") ||
    categories.has("escalation")
  ) {
    bonus += 1;
  }

  return Math.min(bonus, 2);
}

function baseStageForTurn(turn) {
  if (turn >= MAX_TURNS) return FINAL_STAGE;
  if (turn < 1) return 1;
  return Math.min(STAGE_COUNT, Math.ceil(turn / 2));
}

function computeStage(turn, text, previousStage) {
  if (turn >= MAX_TURNS) return FINAL_STAGE;
  const base = baseStageForTurn(turn);
  const stage = Math.min(STAGE_COUNT, base + escalationBonus(text));
  return Math.min(STAGE_COUNT, Math.max(previousStage, stage));
}

function pick(pool, key) {
  if (!pool || pool.length === 0) return "";
  if (pool.length === 1) return pool[0];

  let index = Math.floor(Math.random() * pool.length);
  if (index === lastPick.get(key)) {
    index = (index + 1) % pool.length;
  }
  lastPick.set(key, index);
  return pool[index];
}

function chooseHook(text, stage) {
  if (stage >= 5) return "";

  const categories = detectKeywords(text);
  const priority =
    stage <= 3
      ? ["legal", "leave", "escalation", "money", "hardware", "speed"]
      : ["legal", "leave", "escalation", "money"];
  const category = priority.find((name) => categories.has(name));
  if (!category) return "";

  if (category === state.lastHookCategory && Math.random() < 0.65) return "";
  state.lastHookCategory = category;
  return pick(HOOKS[category], `hook-${category}`);
}

function buildReply(stage, text, turn) {
  if (turn >= MAX_TURNS || stage >= FINAL_STAGE) {
    return pick(FINAL_REPLIES, "final");
  }

  if (turn === 1 && stage === 1) {
    return pick(OPENING_REPLIES, "opening");
  }

  const hook = chooseHook(text, stage);
  const core = pick(STAGE_REPLIES[stage], `stage-${stage}`);
  return hook ? `${hook} ${core}` : core;
}

function scrollToBottom() {
  chat.scrollTo({
    top: chat.scrollHeight,
    behavior: REDUCED_MOTION ? "auto" : "smooth",
  });
}

function addMessage(text, role) {
  const message = document.createElement("article");
  message.className = `message message-${role}`;
  message.setAttribute("aria-label", role === "bot" ? "Артём" : "Вы");

  const bubble = document.createElement("div");
  bubble.className = "bubble";
  bubble.textContent = text;

  message.appendChild(bubble);
  chat.appendChild(message);
  scrollToBottom();
}

function addSystemMessage(text) {
  const message = document.createElement("p");
  message.className = "system-message";
  message.textContent = text;
  chat.appendChild(message);
  scrollToBottom();
}

function showTyping() {
  hideTyping();

  const message = document.createElement("div");
  message.className = "message message-bot typing";
  message.id = "typing-indicator";
  message.setAttribute("role", "status");

  const bubble = document.createElement("div");
  bubble.className = "bubble";

  const label = document.createElement("span");
  label.className = "typing-label";
  label.textContent = "Артём печатает";

  const dots = document.createElement("span");
  dots.className = "dots";
  dots.setAttribute("aria-hidden", "true");
  for (let index = 0; index < 3; index += 1) {
    dots.appendChild(document.createElement("span"));
  }

  bubble.append(label, dots);
  message.appendChild(bubble);
  chat.appendChild(message);
  chat.setAttribute("aria-busy", "true");
  scrollToBottom();
}

function hideTyping() {
  const typing = document.getElementById("typing-indicator");
  if (typing) typing.remove();
  chat.setAttribute("aria-busy", "false");
}

function updateCounter() {
  const length = input.value.length;
  charCounter.textContent = `${length} / ${MAX_CHARS}`;
  charCounter.classList.toggle("is-full", length >= MAX_CHARS);
}

function updateMeta() {
  if (state.stage >= FINAL_STAGE) {
    stageBadge.dataset.stage = "7";
    stageBadge.textContent = state.ended
      ? "Капитуляция · диалог завершён"
      : "Капитуляция · Артём сдаётся";
  } else {
    const meta = STAGE_META[state.stage] || STAGE_META[1];
    stageBadge.dataset.stage = String(state.stage);
    stageBadge.textContent = `Стадия ${state.stage} из ${STAGE_COUNT} · ${meta.label}`;
  }
  turnCounter.textContent = `Ход ${state.turn} из ${MAX_TURNS}`;
}

function setBusy(busy) {
  state.busy = busy;
  const disabled = busy || state.ended;
  input.disabled = disabled;
  sendButton.disabled = disabled;
  quickReplies.querySelectorAll("button").forEach((button) => {
    button.disabled = disabled;
  });
}

function renderQuickReplies() {
  quickReplies.replaceChildren();

  if (state.ended) {
    quickReplies.hidden = true;
    return;
  }

  const suggestions = QUICK_REPLIES[state.stage] || [];
  if (suggestions.length === 0) {
    quickReplies.hidden = true;
    return;
  }

  quickReplies.hidden = false;
  for (const text of suggestions) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "quick-reply";
    button.textContent = text;
    button.disabled = state.busy;
    button.addEventListener("click", () => sendMessage(text));
    quickReplies.appendChild(button);
  }
}

function setEndedUI() {
  input.placeholder = "Диалог завершён — нажмите «Начать заново»";
  input.disabled = true;
  sendButton.disabled = true;
  quickReplies.replaceChildren();
  quickReplies.hidden = true;
}

function sendMessage(rawText) {
  if (state.busy || state.ended) return;

  const text = String(rawText ?? "")
    .replace(/\s+/g, " ")
    .trim()
    .slice(0, MAX_CHARS);

  if (!text) {
    input.focus({ preventScroll: true });
    return;
  }

  addMessage(text, "user");
  input.value = "";
  updateCounter();

  state.turn = Math.min(state.turn + 1, MAX_TURNS);
  state.stage = computeStage(state.turn, text, state.stage);

  setBusy(true);
  updateMeta();
  showTyping();

  const reply = buildReply(state.stage, text, state.turn);
  const delay = REDUCED_MOTION ? 300 : 300 + Math.random() * 600;

  replyTimer = window.setTimeout(() => {
    hideTyping();
    addMessage(reply, "bot");

    if (state.turn >= MAX_TURNS) {
      state.ended = true;
      setBusy(false);
      addSystemMessage(
        "Диалог завершён. Артём сломался и ушёл за чаем. «Начать заново» — новый заход.",
      );
      setEndedUI();
      updateMeta();
    } else {
      setBusy(false);
      renderQuickReplies();
      updateMeta();
      input.focus({ preventScroll: true });
    }
  }, delay);
}

function start() {
  window.clearTimeout(replyTimer);
  state = freshState();
  lastPick.clear();

  chat.replaceChildren();
  input.value = "";
  input.placeholder = "Напишите в поддержку…";
  updateCounter();
  updateMeta();

  setBusy(true);
  renderQuickReplies();
  addSystemMessage(
    "Демо-режим: ответы заранее написаны, сетевых запросов нет. Сценарий — 6 стадий и капитуляция.",
  );
  showTyping();

  replyTimer = window.setTimeout(() => {
    hideTyping();
    addMessage(GREETING, "bot");
    setBusy(false);
    renderQuickReplies();
    updateMeta();
    input.focus({ preventScroll: true });
  }, REDUCED_MOTION ? 300 : 550);
}

input.addEventListener("input", () => {
  if (input.value.length > MAX_CHARS) {
    input.value = input.value.slice(0, MAX_CHARS);
  }
  updateCounter();
});

form.addEventListener("submit", (event) => {
  event.preventDefault();
  sendMessage(input.value);
});

resetButton.addEventListener("click", start);

start();
