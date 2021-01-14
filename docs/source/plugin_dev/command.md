# Command

Tired of manually splitting argument and parsing commands? Being annoyed by the complicated argument conditions? Go try the MCDR command building system!

MCDR contains a command tree building system for plugins to build their commands. It behaves like a lite version of mojang's [brigadier](https://github.com/Mojang/brigadier)

## A Quick Peek

Let's peek into the actual operation of a command tree. As an example, let's say that there are 3 kinds of commands:

- `!!email list`
- `!!email remove <email_id>`
- `!!email send <player> <message>`

To implement these commands, we can build a command tree with MCDR like this:

```
Literal('!!email')
 ├─ Literal('list')
 ├─ Literal('remove')
 │   └─ Integer('email_id')
 └─ Literal('send')
     └─ Text('player')
         └─ GreedyText('message')
```

When MCDR executes the command `!!email remove 21`, the following things will happen

1. Parsing at node `Literal('!!email')` with command `!!email remove 21`
    1. Literal Node `Literal('!!email')` gets the first element of `!!email remove 21`, it's `!!email` and it matches the literal node  
    2. Now the remaining command is `remove 21`
    3. And then, it searches through its literal children, found the child node `Literal('remove')` matches the next literal element `remove`  
    4. Then it let that child node to handle the rest of the command
2. Parsing at node `Literal('remove')` with command `remove 21`
    1. Literal Node `Literal('remove')` gets the first element of `remove 21`, it's `remove` and it matches the literal node
    2. Now the remaining command is `21`
    3. And then it searches through its literal children, but doesn't found any literal child matches the next element `21`
    4. So it let its non-literal child `Integer('email_id')` to handle the rest of the command
3. Parsing at node `Integer('email_id')` with command `21`
    1. Integer Node `Integer('email_id')` gets the first element of `21`, it's a legal integer
    2. It store the value `21` to the context dict with key `email_id`
    3. And then it finds that the command parsing is already finished so it invokes the callback function with the command source and the context dict as the argument.
    4. The command parsing finishes

This is a quick overview of the implantation logic part of command building system. It's mainly for help you build a perceptual understanding of the command tree based command building system

Matching the literal nodes, parsing the remaining command, storing the parsed value inside the context dict, this is how the command system works

Rather than reading this document, anther good way to learn to use the MCDR command building system is to refer and imitate existing codes. You can find the command building code of `!!MCDR` command in the `__register_commands` method of class `mcdreforged.plugin.permanent.mcdreforged_plugin.MCDReforgedPlugin`

## Argument Nodes

A list of MCDR built-in argument nodes and their usage

### ArgumentNode

Argument Node is base node of all argument nodes. It's also a abstract class. It provides several methods for building up the command tree

#### then

```python
def then(self, node: 'ArgumentNode') -> ArgumentNode
```

Attach a child node to its children list, and then return itself

It's used for building the command tree structure

Parameter *node*: A node instance to be added to current node's children list

The command tree in the [Quick Peek](#a-quick-peek) section can be built with the following codes

```python
Literal('!!email'). \
then(
    Literal('list')
). \
then(
    Literal('remove').
    then(
        Integer('email_id')
    )
). \
then(
    Literal('send').
    then(
        Text('player').
        then(
            GreedyText('message')
        )
    )
)
```

#### runs

```python
def runs(self, func: Union[Callable[[], Any], Callable[[CommandSource], Any], Callable[[CommandSource, dict], Any]]) -> ArgumentNode
```

Set the callback function of this node. When the command parsing finished at this node, the callback function will be executed

Parameter *func*: A callable that accepts up to 2 arguments. Argument list: `CommandSource`, `dict` (context)

The callback function is allowed to accepted 0 to 2 arguments (a `CommandSource` as command source and a `dict` as context). For example, the following 4 functions are available callbacks

```python
def callback1():
    pass

def callback2(source: CommandSource):
    pass

def callback3(source: CommandSource, context: dict):
    pass

callback4 = lambda src: src.reply('pong')
node1.runs(callback1)
node2.runs(callback2)
node3.runs(callback3)
node4.runs(callback4)
```

Both of them can be used as the argument of the `runs` method

This dynamic callback argument adaptation is used in all callback invoking of the command nodes

#### requires

```python
def requires(self, requirement: Union[Callable[[], bool], Callable[[CommandSource], bool], Callable[[CommandSource, dict], bool]], failure_message_getter: Optional[Union[Callable[[], str], Callable[[CommandSource], str], Callable[[CommandSource, dict], str]]] = None) -> ArgumentNode
```

Set the requirement tester callback of the node. When entering this node, MCDR will invoke the requirement tester to see if the current command source and context match your specific condition.

If the tester callback return True, nothing will happen, MCDR will continue parsing the rest of the command

If the tester callback return False, a `RequirementNotMet` exception will be risen. At this time if the *failure_message_getter* parameter is available, MCDR will invoke *failure_message_getter* to get the message string as the `RequirementNotMet` exception, otherwise a default message will be used

Parameter *requirement*: A callable that accepts up to 2 arguments and returns a bool. Argument list: `CommandSource`, `dict` (context)

Parameter *failure_message_getter*: An optional callable that accepts up to 2 arguments and returns a str. Argument list: `CommandSource`, `dict` (context)

Some Example usages:

```python
node.requires(lambda src: src.has_permission_level(3))  # Permission check
node.requires(lambda src, ctx: ctx['page_count'] <= get_max_page())  # Dynamic range check
node.requires(lambda src, ctx: is_legal(ctx['target']), lambda src, ctx: 'target {} is illegal'.format(ctx['target']))  # Customized failure message
```

#### redirects

```python
def redirects(self, redirect_node: ArgumentNode) -> ArgumentNode
```

Redirect all further child nodes command parsing to another given node. When you want a short command and and full-path command that will all execute the same commands, `redirects` will make it simpler

Parameter *redirect_node*: A node instance which current node is redirecting to

Examples:

```python
command_node = Literal('command'). \
    then(Literal('x').runs(do_something1)). \
    then(Literal('y').runs(do_something2)). \
    then(Literal('z').runs(do_something3))

long_node = Literal('a').then(Literal('long').then(Literal('way').then(Literal('to').then(Literal('the').then(command_node)))))
short_node = Literal('quick').redirects(command_node)

root_executor = Literal('foo').then(long_node).then(short_node)
```

Command starts at *root_executor*

These commands:

- "foo a long way to the command x"
- "foo a long way to the command y"
- "foo a long way to the command z"

are the same to

- "foo quick x"
- "foo quick y"
- "foo quick z"

Pay attention to the difference between `redirects` and `then`. `redirects` is to redirect the child nodes, and `then` is to add a child node. If you do something like this:

```python
short_node2 = Literal('fast').then(command_node)
root_executor = Literal('foo').then(long_node).then(short_node).then(short_node2)
```

Then all commands which eventually executes `do_something1` will be:

- `foo a long way to the command x`
- `foo quick x`
- `foo fast command x`


#### on_error

```python
def on_error(self, error_type: Type[CommandError], handler: Union[Callable[[], Any], Callable[[CommandSource], Any], Callable[[CommandSource, CommandError], Any], Callable[[CommandSource, CommandError, dict], Any]], *, handled: bool = False) -> ArgumentNode
```

When a command error occurs, the given will invoke the given handler to handle with the error

Parameter *error_type*: A class that is subclass of CommandError

Parameter *handler*: A callable that accepts up to 3 arguments. Argument list: `CommandSource`, `CommandError`, `dict` (context)

Keyword Parameter *handled*: If handled is set to True, `error.set_handled()` is called automatically when invoking the handler callback

For uses about `error.set_handled()`, check the [CommandError](classes/CommandError.html#set-handled) class reference

### Literal

Literal node is a special node. It doesn't output any value. It's more like a command branch carrier

Literal node can accept a str as its literal in its constructor. A literal node accepts the parsing command only when the next element of the parsing command exactly matches the literal of the node

Literal node is the only node that can start a command execution

Examples:

```python
Literal('foo').runs(lambda src: src.reply('Foo!'))  # input "foo", get reply "Foo!"
Literal('foo').then(
    Literal('bar').runs(lambda src: src.reply('Foo Bar'))
)  # input "foo bar", get reply "Foo Bar"
```

### NumberNode

It's an abstract class. It's inherited by `Number`, `Integer` and `Float`. It represents a type of number based node

For a `NumberNode` instance, you can restrict the range of the number argument. If the parsed number is out of range, a `NumberOutOfRange` exception will be risen

By default there's no range restriction

#### at_min

```python
def at_min(self, min_value) -> NumberNode
```

Set the lower boundary of the range restriction to *min_value*

#### at_max

```python
def at_max(self, max_value) -> NumberNode
```

Set the higher boundary of the range restriction to *max_value*

#### in_range

```python
def in_range(self, min_value, max_value) -> NumberNode
```

Set the lower and the higher boundary of the range restriction at the same time

### Number

A `Number` node accepts a number argument. It can be an integer or an float. If the next element is not a number, a `InvalidNumber` exception will be risen

### Integer

An `Integer` node accepts a int argument. It can only be an integer. If the next element is not an integer, a `InvalidInteger` exception will be risen

### Float

A `Float` node accepts a float argument. It can only be a float. If the next element is not a float, a `InvalidFloat` exception will be risen

### TextNode

It's an abstract class. It's inherited by `Text`, `QuotableText` and `GreedyText`. It represents a type of text based node

For a `TextNode` instance, you can restrict the length range of the str text argument. If the length of the parsed text is out of range, a `TextLengthOutOfRange` exception will be risen

By default there's no length range restriction

#### at_min_length

```python
def at_min_length(self, min_length) -> TextNode
```

Set the lower boundary of the length range restriction to *min_length*

#### at_max_length

```python
def at_max_length(self, max_length) -> TextNode
```

Set the higher boundary of the length range restriction to *max_length*

#### in_length_range

```python
def in_length_range(self, min_length, max_length) -> TextNode
```

Set the lower and the higher boundary of the length range restriction at the same time

### Text

A `Text` node accepts a single string element. Since space character is the divider character of MCDR command parsing. `Text` nodes will keep taking the continuous string segment until they meet a space character

### QuotableText

A `QuotableText` works just like a `Text` argument node, but it gives user a way to input text with space character: Use two double quotes to enclose the text content

If you use two double quotes to enclose the text content, You can use escape character `\` to escape double quotes `"` and escape character `\` itself

For example, here are some texts that accepted by `QuotableText`:

- `Something`
- `"Someting with space characters"`
- `"or escapes \\ like \" this"`

### GreedyText

The principle of `GreedyText` is quite simple: It greedily take out all remaining texts in the commands

It's not a smart decision to append any child nodes to a `GreedyText`, since the child nodes can never get any remaining command

## Customize

MCDR also supports customize an argument node. It might save you same repeated work on building your command

To create a custom a argument node, you need to declare a class inherited from `ArgumentNode`, and then implement the `parse` method logic. That's it, the custom node class is ready to be used

Custom exception provides a precise way to handle your exception with `on_error` method. If you want to raise a custom exception when your argument node fails to parsing the text, you need to have the custom exception inherited from `CommandSyntaxError`

Here's a quick example of a custom Argument node, `PointArgument`. It accepts continuous 3 float input as a coordinate and batch them in to a list as a point. It raises `IllegalPoint` if it gets a non-float input, or `IncompletePoint` if the command ends before it finishes reading 3 floats

```python
class IllegalPoint(CommandSyntaxError):
	def __init__(self, char_read: int):
		super().__init__('Invalid Point', char_read)


class IncompletePoint(CommandSyntaxError):
	def __init__(self, char_read: int):
		super().__init__('Incomplete Point', char_read)


class PointArgument(ArgumentNode):
	def parse(self, text: str) -> ParseResult:
		total_read = 0
		coords = []
		for i in range(3):
			value, read = command_builder_util.get_float(text[total_read:])
			if read == 0:
				raise IncompletePoint(total_read)
			total_read += read
			if value is None:
				raise IllegalPoint(total_read)
			coords.append(value)
		return ParseResult(coords, total_read)
```

For its usage, here's a simple example as well as an input/output table:

```python
def on_load(server, prev):
    server.register_command(
        Literal('!!mypoint').then(
            PointArgument('pt').
            runs(lambda src, ctx: src.reply('You have input a point ({}, {}, {})'.format(*ctx['pt'])))
        )
    )
```

| Input | Output |
| --- | --- |
| !!mypoint 1 2 3 | You have input a point (1.0, 2.0, 3.0) |
| !!mypoint 1 2 | Incomplete Point: !!mypoint 1 2<-- |
| !!mypoint xxx | Invalid Point: !!mypoint xxx<-- |
| !!mypoint 1 2 x | Invalid Point: !!mypoint 1 2 x<-- |