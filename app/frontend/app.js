const form = document.querySelector("#task-form");
const input = document.querySelector("#task-title");
const list = document.querySelector("#task-list");
const count = document.querySelector("#task-count");
const emptyState = document.querySelector("#empty-state");
const feedback = document.querySelector("#feedback");
const connection = document.querySelector("#connection");

function formatCount(total) {
  const mod10 = total % 10;
  const mod100 = total % 100;
  const word = mod10 === 1 && mod100 !== 11 ? "задача" :
    mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14) ? "задачи" : "задач";
  return `${total} ${word}`;
}

function renderTasks(tasks) {
  list.replaceChildren();
  for (const task of tasks) {
    const item = document.createElement("li");
    const title = document.createElement("span");
    title.className = "task-title";
    title.textContent = task.title;
    const date = document.createElement("time");
    date.className = "task-date";
    date.dateTime = task.created_at;
    date.textContent = new Intl.DateTimeFormat("ru", { dateStyle: "medium" }).format(new Date(task.created_at));
    item.append(title, date);
    list.append(item);
  }
  count.textContent = formatCount(tasks.length);
  emptyState.hidden = tasks.length > 0;
}

async function loadTasks() {
  const response = await fetch("/api/tasks");
  if (!response.ok) throw new Error("Не удалось загрузить список.");
  renderTasks(await response.json());
  connection.textContent = "база на связи";
  connection.className = "status ok";
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  feedback.textContent = "";
  const button = form.querySelector("button");
  button.disabled = true;
  try {
    const response = await fetch("/api/tasks", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title: input.value }),
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || "Не удалось сохранить задачу.");
    input.value = "";
    await loadTasks();
    input.focus();
  } catch (error) {
    feedback.textContent = error.message;
  } finally {
    button.disabled = false;
  }
});

loadTasks().catch((error) => {
  feedback.textContent = error.message;
  connection.textContent = "база не отвечает";
  connection.className = "status error";
});
