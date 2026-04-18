# JEEVES_PROJECT_SPEC

## 1. Назначение

Jeeves — это агент, работающий в обычном чате.

Перед тем как что-либо делать, Jeeves должен сначала перевести пользовательский запрос в короткую, отчётливую, удобную для машинной обработки формулировку на английском языке, показать её пользователю, принять правки и только после этого решить, может ли он выполнить задачу сам или нужно привлекать дополнительные средства выполнения.

Jeeves не строится вокруг ролевой модели и не использует продуктовую таксономию `chat / research / write / next_step` как основу. Основа Jeeves — это нормализация пользовательского запроса, корректировка этого понимания через обычный чат, решение о выполнении, выполнение и трёхслойная память.

Спецификация потока понимания (Phase 1): `docs/UNDERSTANDING_FLOW.md`.

## 2. Главная идея продукта

Пользователь пишет как обычно.

Jeeves не отвечает сразу по существу, если запрос ещё не зафиксирован. Сначала Jeeves делает запрос отчётливо понятным в короткой английской форме.

Пример:

Пользователь:
> Напиши клиенту, что срок сдвигается.

Jeeves:
> I understood the request as: `write short client delay message`  
> Continuity: `new`  
> Clarification: not needed.

Пользователь:
> Не просто delay, а на два дня.

Jeeves:
> Updated request: `write short client message about two-day delay`

После этого Jeeves переходит к решению, может ли выполнить задачу сам.

## 3. Базовый цикл

1. Пользователь пишет сообщение.
2. LLM строит `NormalizedUserRequest`.
3. Контракт валидируется.
4. Jeeves показывает результат пользователю.
5. Пользователь либо молчит, либо вносит поправки.
6. При правках строится новая версия того же `NormalizedUserRequest`.
7. После подтверждения запускается `ExecutionDecision`.
8. Агент либо выполняет задачу сам, либо понимает, что ему нужно для выполнения.
9. После выполнения обновляется память.
10. После завершения чата запускается post-chat memory analysis.

## 4. Scope проекта v1

В v1 должны быть реализованы обычный чат, первый слой `NormalizedUserRequest`, correction loop через обычный чат, второй слой `ExecutionDecision`, short-term chat memory, long-term memory, core profile, explicit memory commands вида `запомни это`, post-chat background memory analysis, подтверждение memory candidates пользователем и orchestration на LangGraph.

В v1 не нужно делать сложную систему ролей, продуктовую mode taxonomy как основную абстракцию, много внешних интеграций, автоматическое сохранение всего подряд в глубокую память, сложный UI-конструктор форм вместо обычного чата и многоагентную архитектуру высокого уровня.

## 5. Основные сущности

### 5.1 NormalizedUserRequest

Первый и главный объект входного слоя.

```python
from typing import Literal, List
from pydantic import BaseModel


class NormalizedUserRequest(BaseModel):
    normalized_user_request: str
    continuity: Literal["new", "continue", "correct_previous", "unclear"]
    needs_clarification: bool
    clarification_reason: str | None = None
    clarification_options: List[str] = []
    ambiguity_handling: Literal["none", "ask_user", "answer_with_options"]
    revision: int = 1
```

Смысл:
- `normalized_user_request` — короткая машинно-удобная английская формулировка;
- `continuity` — новая тема или продолжение;
- `needs_clarification` — можно ли идти дальше;
- `clarification_reason` — почему нужна ясность;
- `clarification_options` — варианты трактовки;
- `ambiguity_handling` — спрашивать пользователя или показать варианты;
- `revision` — версия после правок.

### 5.2 ExecutionDecision

Второй слой. Главный вопрос: может ли агент выполнить задачу сам?

```python
from pydantic import BaseModel


class ExecutionDecision(BaseModel):
    can_execute_self: bool
    needs_external_info: bool
    needs_tool: bool
    needs_delegate: bool
    needs_decomposition: bool
    needs_user_confirmation: bool
    reason: str
```

### 5.3 MemoryCandidate

Кандидат на запись в long-term memory или core profile.

```python
from typing import Literal
from pydantic import BaseModel


class MemoryCandidate(BaseModel):
    memory_type: Literal["fact", "preference", "rule"]
    target_layer: Literal["long_term_memory", "core_profile"]
    normalized_memory: str
    source: Literal["user_requested", "post_chat_analysis"]
    confidence: float
    requires_confirmation: bool = True
```

### 5.4 MemoryEntry

Подтверждённая запись памяти.

```python
from typing import Literal
from pydantic import BaseModel


class MemoryEntry(BaseModel):
    memory_type: Literal["fact", "preference", "rule"]
    target_layer: Literal["long_term_memory", "core_profile"]
    normalized_memory: str
    source: Literal["user_requested", "post_chat_analysis"]
    status: Literal["confirmed", "rejected", "archived"]
```

### 5.5 ChatState

Главное состояние графа LangGraph для одного чата.

```python
from typing import Optional, List, Literal
from pydantic import BaseModel


class ChatState(BaseModel):
    chat_id: str
    user_id: str

    raw_user_message: str | None = None

    normalized_request: Optional[NormalizedUserRequest] = None
    normalized_request_history: List[NormalizedUserRequest] = []

    awaiting_user_feedback: bool = False
    awaiting_confirmation: bool = False

    execution_decision: Optional[ExecutionDecision] = None
    execution_status: Literal["idle", "pending", "running", "completed", "blocked"] = "idle"

    assistant_messages: List[str] = []
    user_corrections: List[str] = []

    explicit_memory_command: bool = False
    memory_candidates: List[MemoryCandidate] = []

    chat_closed: bool = False
```

## 6. Три уровня памяти

### 6.1 Chat Memory

Память текущего чата.

Хранит сообщения, текущий `NormalizedUserRequest`, revision history, текущие corrections, текущий `ExecutionDecision`, текущий контекст выполнения и текущее состояние графа.

### 6.2 Long-Term Memory

Память между чатами.

Хранит важные факты, устойчивые пользовательские предпочтения, повторяющиеся паттерны, рабочие правила и кандидаты на память.

### 6.3 Core Profile

Самый глубокий слой.

Это не просто память, а операционный профиль ассистента.

Хранит устойчивые preferences, communication defaults, operating rules, action governance, trust / decision policy и memory update policy.

## 7. Как должна работать нормализация

На входе не должно быть механического парсинга. На входе стоит LLM.

Сырый запрос пользователя сначала получает LLM и строит только `NormalizedUserRequest`.

Pydantic или PydanticAI не понимает смысл сообщения сам. Он валидирует уже полученную структуру.

Примеры:

#### Пример 1

Пользователь:
> Как тебя зовут?

```json
{
  "normalized_user_request": "ask assistant name",
  "continuity": "new",
  "needs_clarification": true,
  "clarification_reason": "request may refer to model name, assistant name in this chat, or another identity label",
  "clarification_options": [
    "model_name",
    "assistant_name_in_this_chat",
    "other_identity_label"
  ],
  "ambiguity_handling": "answer_with_options",
  "revision": 1
}
```

#### Пример 2

Пользователь:
> Какая сегодня погода в Берлине?

```json
{
  "normalized_user_request": "get today's weather in Berlin",
  "continuity": "new",
  "needs_clarification": false,
  "clarification_reason": null,
  "clarification_options": [],
  "ambiguity_handling": "none",
  "revision": 1
}
```

#### Пример 3

Пользователь:
> Нет, это тот же клиентский тред.

```json
{
  "normalized_user_request": "correct previous framing: continue same client task",
  "continuity": "correct_previous",
  "needs_clarification": false,
  "clarification_reason": null,
  "clarification_options": [],
  "ambiguity_handling": "none",
  "revision": 2
}
```

## 8. Поведение при неоднозначности

Если запрос неоднозначен, Jeeves обязан выбрать один из двух вариантов:

- `ask_user`
- `answer_with_options`

### ask_user

Jeeves задаёт уточняющий вопрос.

Пример:
> Do you mean the model name or the assistant name in this chat?

### answer_with_options

Jeeves не спрашивает сразу, а перечисляет варианты.

Пример:
> If you mean the assistant name in this chat, it is Jeeves. If you mean the model name, that is different.

## 9. Correction loop

Пользователь должен иметь возможность исправить понимание обычным сообщением.

Пример:

Jeeves:
> I understood the request as: `write short client delay message`

Пользователь:
> Не просто delay, а на два дня.

Jeeves:
> Updated request: `write short client message about two-day delay`

Правило:
- корректировка не создаёт новый тип объекта;
- она создаёт новую revision того же `NormalizedUserRequest`.

## 10. Решение о выполнении

После подтверждённого `NormalizedUserRequest` Jeeves задаёт главный вопрос:

**может ли агент выполнить это сам?**

Если да, идёт в выполнение.

Если нет, определяет причину и решает, нужен ли интернет, нужен ли tool, нужен ли delegate, нужна ли декомпозиция, нужно ли пользовательское подтверждение.

Это уже второй слой и он не должен переопределять первый.

## 11. Работа с памятью

### 11.1 Явная команда пользователя

Если пользователь пишет:
> Запомни это.

Jeeves обязан:
1. переформулировать, что именно он собирается запомнить;
2. показать это пользователю;
3. только потом сохранить.

Пример:

Пользователь:
> Запомни, что мне обычно нужен один конкретный следующий шаг.

Jeeves:
> I will store this as: `user prefers one concrete next step`  
> Target layer: `core_profile`  
> Confirm?

### 11.2 Background memory analysis

После завершения чата background-задача анализирует чат и предлагает memory candidates.

Она должна:
1. просмотреть chat memory;
2. выделить кандидаты;
3. классифицировать их как `fact`, `preference`, `rule`;
4. определить, это long-term memory или core profile;
5. сохранить кандидаты в статусе pending / candidate;
6. дождаться пользовательского подтверждения.

## 12. LangGraph как orchestration layer

LangGraph является обязательной частью проекта v1 и отвечает за состояние, переходы, ветвления, паузы ожидания пользователя, post-chat flows и координацию памяти.

LangGraph не используется вместо LLM или вместо PydanticAI. Он используется как каркас рантайма.

### Что делает LangGraph

- держит `ChatState`;
- сохраняет continuity одного чата;
- управляет переходами между узлами;
- умеет останавливать граф в точках ожидания пользователя;
- запускает post-chat analysis;
- разделяет online chat loop и background memory loop.

### Что не делает LangGraph

- не заменяет `NormalizedUserRequest`;
- не заменяет Pydantic validation;
- не заменяет LLM;
- не является продуктовой моделью сам по себе.

## 13. Минимальный граф v1

В проекте должно быть минимум два графа.

### 13.1 Main Chat Graph

Узлы:
- `receive_user_message`
- `normalize_user_request`
- `show_normalized_request`
- `wait_for_user_feedback`
- `apply_user_correction`
- `confirm_normalized_request`
- `decide_execution`
- `execute_task`
- `handle_memory_command`
- `close_chat`

### 13.2 Memory Graph

Узлы:
- `post_chat_memory_analysis`
- `create_memory_candidates`
- `store_memory_candidates`
- `review_memory_candidates`
- `confirm_memory_candidate`
- `reject_memory_candidate`
- `write_memory_entry`

## 14. Логика переходов Main Chat Graph

### receive_user_message -> normalize_user_request

Каждое входящее сообщение пользователя сначала идёт в нормализацию.

### normalize_user_request -> show_normalized_request

После генерации и валидации `NormalizedUserRequest` результат показывается пользователю.

### show_normalized_request -> wait_for_user_feedback

Если ожидается реакция пользователя, граф переходит в состояние ожидания.

### wait_for_user_feedback -> apply_user_correction

Если пользователь внёс правку, создаётся новая revision `NormalizedUserRequest`.

### wait_for_user_feedback -> confirm_normalized_request

Если пользователь не возразил или подтвердил, нормализованный запрос считается принятым.

### confirm_normalized_request -> decide_execution

После подтверждения запускается `ExecutionDecision`.

### decide_execution -> execute_task

Если `can_execute_self = true`, начинается выполнение.

### decide_execution -> wait_for_user_feedback

Если нужно подтверждение пользователя или дополнительное уточнение, граф возвращается в ожидание.

### execute_task -> close_chat

После завершения выполнения чат может быть закрыт или остаться активным.

### close_chat -> post_chat_memory_analysis

После закрытия чата запускается memory graph.

## 15. Backend-модули

### app/domain
- `normalized_user_request.py`
- `execution_decision.py`
- `memory_candidate.py`
- `memory_entry.py`
- `chat_state.py`
- `core_profile.py`

### app/agents
- `normalization_agent.py`
- `execution_agent.py`
- `memory_agent.py`

### app/graph
- `main_chat_graph.py`
- `memory_graph.py`
- `graph_factory.py`

### app/services
- `chat_service.py`
- `execution_service.py`
- `memory_service.py`
- `profile_service.py`

### app/repositories
- `chat_repository.py`
- `memory_repository.py`
- `profile_repository.py`

### app/api
- `chat.py`
- `memory.py`
- `profile.py`

### app/tasks
- `post_chat_analysis.py`

## 16. Рекомендуемый стек

- Python
- FastAPI
- Pydantic v2
- PydanticAI
- LangGraph
- PostgreSQL
- SQLAlchemy или SQLModel
- Alembic
- Redis для фоновых задач
- React / Next.js для клиента
- Tailwind для UI

## 17. Почему здесь нужен LangGraph

LangGraph нужен не для первого парсинга текста, а для управления состоянием и переходами.

Он должен использоваться для:
- chat loop;
- confirmation loop;
- clarification loop;
- execution routing;
- memory write flows;
- post-chat analysis flows.

## 18. База данных

### chats
- `id`
- `user_id`
- `status`
- `created_at`
- `closed_at`

### messages
- `id`
- `chat_id`
- `actor`
- `content`
- `created_at`

### normalized_requests
- `id`
- `chat_id`
- `message_id`
- `revision`
- `normalized_user_request`
- `continuity`
- `needs_clarification`
- `clarification_reason`
- `clarification_options_json`
- `ambiguity_handling`
- `created_at`

### execution_decisions
- `id`
- `chat_id`
- `normalized_request_id`
- `can_execute_self`
- `needs_external_info`
- `needs_tool`
- `needs_delegate`
- `needs_decomposition`
- `needs_user_confirmation`
- `reason`
- `created_at`

### memory_candidates
- `id`
- `chat_id`
- `memory_type`
- `target_layer`
- `normalized_memory`
- `source`
- `confidence`
- `status`
- `created_at`

### memory_entries
- `id`
- `user_id`
- `memory_type`
- `target_layer`
- `normalized_memory`
- `source`
- `status`
- `created_at`

### core_profile_entries
- `id`
- `user_id`
- `key`
- `value_json`
- `source`
- `status`
- `updated_at`

## 19. API

### POST /chat/message
Принимает пользовательское сообщение и запускает main chat graph с первой ноды.

### POST /chat/correction
Принимает пользовательскую правку и продолжает graph через correction path.

### POST /chat/confirm
Подтверждает текущую revision и запускает `ExecutionDecision`.

### POST /memory/store
Явное сохранение памяти после команды `запомни`.

### GET /memory/candidates
Возвращает memory candidates после post-chat анализа.

### POST /memory/candidates/{id}/confirm
Подтверждает кандидата.

### POST /memory/candidates/{id}/reject
Отклоняет кандидата.

### GET /profile
Возвращает core profile пользователя.

## 20. Frontend

Основной интерфейс — обычный чат.

Нужны экраны:

### 20.1 Chat Screen
Показывает сообщения, `NormalizedUserRequest`, уточнение или варианты трактовки, corrections и ответы агента.

### 20.2 Memory Review Screen
Показывает memory candidates и кнопки confirm / reject / edit.

### 20.3 Core Profile Screen
Показывает подтверждённые profile entries, историю изменений и источник записи.

## 21. Что кодить первым

### Этап 1
- Pydantic модели
- `NormalizedUserRequest`
- `ExecutionDecision`
- `MemoryCandidate`
- `MemoryEntry`
- `ChatState`

### Этап 2
- normalization agent на PydanticAI
- prompt для первого слоя
- validation
- node `normalize_user_request`

### Этап 3
- main chat graph skeleton на LangGraph
- node `show_normalized_request`
- pause/wait for user feedback
- correction loop
- revision history

### Этап 4
- execution decision agent
- node `decide_execution`
- node `execute_task`

### Этап 5
- chat memory persistence
- long-term memory storage
- explicit memory command flow
- node `handle_memory_command`

### Этап 6
- memory graph
- post-chat background analysis
- memory candidates
- review flow

### Этап 7
- core profile
- правила обновления deep memory

## 22. Что считается готовым v1

v1 готов, если система умеет:
1. принимать обычное сообщение пользователя;
2. строить `NormalizedUserRequest`;
3. показывать его пользователю;
4. принимать правки;
5. строить новую revision;
6. решать, может ли агент выполнить задачу сам;
7. запускать выполнение;
8. хранить chat memory;
9. сохранять явную память по команде пользователя;
10. предлагать memory candidates после завершения чата;
11. поддерживать core profile как отдельный слой;
12. управлять всем этим через LangGraph.

## 23. Короткая формула проекта

Jeeves = chat-first agent with:
- normalized user request,
- correction loop,
- execution decision,
- layered memory,
- LangGraph orchestration.

## 24. Главный принцип реализации

Не переделывать старое.

Делать новый проект с нуля вокруг:
- `NormalizedUserRequest`
- `ExecutionDecision`
- `ChatState`
- `LongTermMemory`
- `CoreProfile`
- `LangGraph`

Старые идеи использовать только как reference, не как основу кодовой базы.
