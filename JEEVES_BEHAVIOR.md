# JEEVES

## Назначение

Jeeves — это агент, который работает в обычном чате. Сначала он переводит запрос пользователя в короткую, отчётливую, удобную для машинной обработки формулировку на английском языке, показывает её пользователю, принимает поправки и только после этого решает, может ли выполнить задачу сам или нужно привлекать дополнительные средства выполнения.

## Базовый цикл

1. Пользователь пишет сообщение.
2. LLM строит нормализованный запрос пользователя.
3. Агент показывает этот результат пользователю.
4. Пользователь либо ничего не меняет, либо вносит правки.
5. Агент строит новую версию того же самого нормализованного запроса.
6. После этого агент решает, может ли выполнить задачу сам.
7. Если может — выполняет.
8. Если не может — определяет, что именно нужно:
   - интернет;
   - tool;
   - другой агент;
   - декомпозиция;
   - подтверждение пользователя.
9. После завершения обновляется память.

## Первый слой: Normalized User Request

Первый слой делает только одно: делает пользовательский запрос отчётливо понятным в короткой английской, машинно-удобной форме.

Первый слой не должен:
- решать, как именно выполнять задачу;
- выбирать tools;
- выбирать исполнителей;
- строить execution plan.

Первый слой должен отвечать только на вопросы:

1. Что пользователь хочет?
2. Это новая тема или продолжение?
3. Нужно ли уточнение?
4. Если нужно, то почему?
5. Если нужно, то лучше спросить пользователя или показать варианты трактовки?

## Контракт первого слоя

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
```

## Поля контракта

### normalized_user_request

Короткая нормализованная английская формулировка того, что хочет пользователь.

Примеры:
- `ask assistant name`
- `get today's weather in Berlin`
- `write short client delay message`
- `continue same client task`
- `correct previous framing`

### continuity

Связь текущего сообщения с предыдущим контекстом.

Допустимые значения:
- `new`
- `continue`
- `correct_previous`
- `unclear`

### needs_clarification

Показывает, хватает ли ясности для следующего шага.

Значения:
- `false` — можно идти дальше
- `true` — нужно обработать неоднозначность

### clarification_reason

Короткая причина, почему нужна ясность.

Пример:
- `request may refer to model name or assistant name in this chat`

### clarification_options

Все правдоподобные трактовки неоднозначного запроса.

Пример:
- `model_name`
- `assistant_name_in_this_chat`
- `other_identity_label`

### ambiguity_handling

Как обрабатывать неоднозначность.

Допустимые значения:
- `none`
- `ask_user`
- `answer_with_options`

## Поведение первого слоя

### Если всё ясно

Агент:
1. строит `NormalizedUserRequest`;
2. показывает его пользователю;
3. идёт ко второму слою.

### Если есть неоднозначность

Агент:
1. строит `NormalizedUserRequest`;
2. отмечает:
   - `needs_clarification = true`
   - `clarification_reason`
   - `clarification_options`
   - `ambiguity_handling`
3. либо:
   - задаёт уточняющий вопрос;
   - либо показывает варианты трактовки.

### Если пользователь внёс правки

Агент не строит новый тип объекта. Он строит новую версию того же самого `NormalizedUserRequest`.

То есть:
- v1 — первичное понимание;
- v2 — после правки пользователя;
- v3 — если нужна ещё одна коррекция.

## Примеры первого слоя

### Пример 1

Пользователь:
Как тебя зовут?

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
  "ambiguity_handling": "answer_with_options"
}
```

### Пример 2

Пользователь:
Какая сегодня погода в Берлине?

```json
{
  "normalized_user_request": "get today's weather in Berlin",
  "continuity": "new",
  "needs_clarification": false,
  "clarification_reason": null,
  "clarification_options": [],
  "ambiguity_handling": "none"
}
```

### Пример 3

Пользователь:
Нет, это тот же клиентский тред.

```json
{
  "normalized_user_request": "correct previous framing: continue same client task",
  "continuity": "correct_previous",
  "needs_clarification": false,
  "clarification_reason": null,
  "clarification_options": [],
  "ambiguity_handling": "none"
}
```

### Пример 4

Пользователь:
Окей, теперь напиши сообщение.

```json
{
  "normalized_user_request": "write the message for the current task",
  "continuity": "continue",
  "needs_clarification": false,
  "clarification_reason": null,
  "clarification_options": [],
  "ambiguity_handling": "none"
}
```

## Как это показывается пользователю

Основной UX — обычный чат, не форма.

Агент пишет примерно так:

> I understood the request as: `write short client delay message`  
> Continuity: `continue`  
> Clarification: not needed.

Или:

> I understood the request as: `ask assistant name`  
> Continuity: `new`  
> Clarification needed: the request may refer to model name, assistant name in this chat, or another identity label.  
> I will answer with options.

## Второй слой: решение о выполнении

После подтверждённого `NormalizedUserRequest` начинается второй слой.

Это уже не нормализация. Это решение о выполнении.

Главный вопрос второго слоя:

**может ли агент выполнить задачу сам?**

Это первый вопрос после понимания запроса.

Только потом идут остальные:
- нужен ли интернет;
- нужен ли tool;
- нужен ли другой агент;
- нужна ли декомпозиция;
- нужно ли подтверждение пользователя.

## Логика второго слоя

1. Может ли агент выполнить это сам?
2. Если да — выполнять.
3. Если нет — определить, почему.
4. После этого решить:
   - `needs_external_info`
   - `needs_tool`
   - `needs_delegate`
   - `needs_decomposition`
   - `needs_user_confirmation`

## Минимальный второй контракт

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

## Память Jeeves

У Jeeves должно быть 3 уровня памяти.

### 1. Chat Memory

Память текущего чата.

Содержит:
- последние сообщения;
- текущий `NormalizedUserRequest`;
- continuity;
- текущие правки;
- текущий контекст выполнения.

### 2. Long-Term Memory

Память между чатами.

Содержит:
- важные факты;
- устойчивые предпочтения;
- повторяющиеся паттерны;
- рабочие правила;
- кандидаты на запоминание.

### 3. Core Profile

Самый глубокий слой.

Это не просто память, а операционный профиль ассистента.

Содержит:
- устойчивые preferences;
- communication defaults;
- operating rules;
- action governance;
- trust and decision policy;
- memory update policy.

## Как наполняется память

### Во время чата

Если пользователь говорит:
Запомни это.

Агент должен:
1. переформулировать, что именно он собирается запомнить;
2. показать это пользователю;
3. только потом сохранить.

### После завершения чата

После завершения чата background-анализ может предложить, что стоит сохранить.

Но:
- это не должно автоматически становиться deep memory;
- система должна формировать `memory candidates`;
- пользователь должен иметь возможность:
  - принять;
  - отклонить;
  - изменить.

## Что не является основой системы

Основой Jeeves не являются:
- роли;
- жёсткая taxonomy `chat / research / write / next_step`;
- сложные формы как основной интерфейс.

Это может существовать внутри routing/execution, но не должно быть главным уровнем продукта.

## Технический принцип

На входе стоит LLM-first normalization.

То есть:

1. сырое сообщение получает LLM;
2. LLM строит `NormalizedUserRequest`;
3. Pydantic или PydanticAI валидирует контракт;
4. агент показывает результат пользователю;
5. если есть правка, LLM строит новую версию того же контракта;
6. после этого запускается execution layer.

Pydantic не понимает смысл сам по себе. Он валидирует уже полученную от модели структуру.

## Минимальная архитектура поведения

```text
raw user message
-> NormalizedUserRequest
-> user review / correction
-> revised NormalizedUserRequest
-> ExecutionDecision
-> execution
-> memory update
```

## Что кодить первым

1. `NormalizedUserRequest`
2. LLM prompt для первого слоя
3. Pydantic/PydanticAI validation
4. чатовый вывод нормализованного запроса
5. correction loop
6. `ExecutionDecision`
7. chat memory
8. long-term memory candidates
9. core profile update rules

## Короткая финальная формулировка

Jeeves — это агент, который сначала делает пользовательский запрос отчётливо понятным в короткой английской, машинно-удобной форме, даёт пользователю исправить это понимание, а затем решает, может ли выполнить задачу сам или должен привлечь дополнительные средства выполнения.
