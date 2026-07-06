const menuToggle = document.querySelector("[data-menu-toggle]");
const nav = document.querySelector("[data-nav]");

if (menuToggle && nav) {
  menuToggle.addEventListener("click", () => {
    const isOpen = menuToggle.getAttribute("aria-expanded") === "true";
    menuToggle.setAttribute("aria-expanded", String(!isOpen));
    nav.classList.toggle("is-open", !isOpen);
  });

  nav.addEventListener("click", (event) => {
    if (event.target.closest("a")) {
      menuToggle.setAttribute("aria-expanded", "false");
      nav.classList.remove("is-open");
    }
  });
}

const chatForm = document.querySelector("#chat-form");
const chatInput = document.querySelector("#chat-input");
const messageList = document.querySelector("#message-list");
const promptButtons = document.querySelectorAll("[data-prompt]");
const handoffButtons = document.querySelectorAll("[data-handoff]");

const revealItems = document.querySelectorAll(".reveal");

if (revealItems.length && "IntersectionObserver" in window) {
  const observer = new IntersectionObserver((entries) => {
    entries.forEach((entry) => {
      if (entry.isIntersecting) {
        entry.target.classList.add("is-visible");
        observer.unobserve(entry.target);
      }
    });
  }, { threshold: 0.18 });

  revealItems.forEach((item) => observer.observe(item));
} else {
  revealItems.forEach((item) => item.classList.add("is-visible"));
}

// Fill the Pokemon-style stat bars once their section scrolls into view.
const statRows = document.querySelectorAll("[data-stat]");

if (statRows.length && "IntersectionObserver" in window) {
  const statObserver = new IntersectionObserver((entries) => {
    entries.forEach((entry) => {
      if (entry.isIntersecting) {
        entry.target.classList.add("is-visible");
        statObserver.unobserve(entry.target);
      }
    });
  }, { threshold: 0.4 });

  statRows.forEach((row) => statObserver.observe(row));
} else {
  statRows.forEach((row) => row.classList.add("is-visible"));
}

// Retro dialogue-box typewriter effect for hero flavor text.
document.querySelectorAll(".type-text").forEach((node) => {
  const fullHtml = node.innerHTML;
  const plain = node.textContent;
  node.textContent = "";
  let i = 0;
  const speed = 32;
  const tick = () => {
    i += 1;
    node.textContent = plain.slice(0, i);
    if (i < plain.length) {
      window.setTimeout(tick, speed);
    } else {
      node.innerHTML = fullHtml;
    }
  };
  window.setTimeout(tick, 400);
});

const replies = [
  "I would first confirm the jurisdiction, the exact date you received notice, and whether the document includes a cure period. Those details usually change the next step.",
  "For attorney review, collect the signed agreement, amendments, notice letter, payment history, related emails, and any calendar dates mentioned in the dispute.",
  "I can draft a matter summary with confirmed facts, open questions, likely legal issues, and documents still needed. This is screening information, not legal advice.",
  "A deadline scan should look for notice periods, response windows, statute of limitations concerns, court dates, and contract cure provisions."
];

function createMessage(text, role, isTyping = false) {
  const article = document.createElement("article");
  article.className = `message ${role}-message${isTyping ? " typing" : ""}`;

  if (role === "assistant") {
    const avatar = document.createElement("img");
    avatar.src = "aurora-sprite.svg";
    avatar.alt = "";
    avatar.width = 40;
    avatar.height = 40;
    article.appendChild(avatar);
  }

  const bubble = document.createElement("div");
  bubble.className = "bubble";

  if (isTyping) {
    const dots = document.createElement("span");
    dots.className = "typing-dots";
    dots.setAttribute("aria-label", "Aurora is thinking");
    dots.innerHTML = "<span></span><span></span><span></span>";
    bubble.appendChild(dots);
  } else {
    const paragraph = document.createElement("p");
    paragraph.textContent = text;
    bubble.appendChild(paragraph);
  }

  article.appendChild(bubble);
  return article;
}

function scrollMessages() {
  if (messageList) {
    messageList.scrollTop = messageList.scrollHeight;
  }
}

function sendMessage(text) {
  if (!text.trim() || !messageList) {
    return;
  }

  messageList.appendChild(createMessage(text.trim(), "user"));
  scrollMessages();

  const typing = createMessage("", "assistant", true);
  messageList.appendChild(typing);
  scrollMessages();

  window.setTimeout(() => {
    typing.remove();
    const reply = replies[Math.floor(Math.random() * replies.length)];
    messageList.appendChild(createMessage(reply, "assistant"));
    scrollMessages();
  }, 650);
}

function requestHandoff() {
  if (!messageList) {
    return;
  }

  messageList.appendChild(createMessage("Please connect me with a human attorney.", "user"));
  scrollMessages();

  const typing = createMessage("", "assistant", true);
  messageList.appendChild(typing);
  scrollMessages();

  window.setTimeout(() => {
    typing.remove();
    messageList.appendChild(createMessage(
      "Understood — flagging this matter for attorney handoff now. Someone will pick up the full conversation history, so you will not need to repeat yourself.",
      "assistant"
    ));
    scrollMessages();
  }, 650);
}

if (chatForm && chatInput) {
  chatForm.addEventListener("submit", (event) => {
    event.preventDefault();
    sendMessage(chatInput.value);
    chatInput.value = "";
    chatInput.focus();
  });
}

promptButtons.forEach((button) => {
  button.addEventListener("click", () => {
    const prompt = button.getAttribute("data-prompt") || "";
    if (chatInput) {
      chatInput.value = prompt;
      chatInput.focus();
    }
    sendMessage(prompt);
    if (chatInput) {
      chatInput.value = "";
    }
  });
});

handoffButtons.forEach((button) => {
  button.addEventListener("click", requestHandoff);
});
