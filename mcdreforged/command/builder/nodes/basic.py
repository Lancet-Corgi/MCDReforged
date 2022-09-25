import collections
import inspect
from abc import ABC
from types import MethodType
from typing import List, Callable, Iterable, Set, Dict, Type, Any, Union, Optional, NamedTuple

from mcdreforged.command.builder import command_builder_util as utils
from mcdreforged.command.builder.common import ParseResult, CommandContext, CommandSuggestions, CommandSuggestion
from mcdreforged.command.builder.exception import LiteralNotMatch, UnknownCommand, UnknownArgument, CommandSyntaxError, \
	UnknownRootArgument, RequirementNotMet, IllegalNodeOperation, \
	CommandError
from mcdreforged.command.command_source import CommandSource
from mcdreforged.utils import misc_util, tree_printer
from mcdreforged.utils.types import MessageText

__SOURCE_CONTEXT_CALLBACK = Union[Callable[[], Any], Callable[[CommandSource], Any], Callable[[CommandSource, dict], Any]]
__SOURCE_CONTEXT_CALLBACK_BOOL = Union[Callable[[], bool], Callable[[CommandSource], bool], Callable[[CommandSource, dict], bool]]
__SOURCE_CONTEXT_CALLBACK_MSG = Union[Callable[[], MessageText], Callable[[CommandSource], MessageText], Callable[[CommandSource, dict], MessageText]]
__SOURCE_CONTEXT_CALLBACK_STR_ITERABLE = Union[Callable[[], Iterable[str]], Callable[[CommandSource], Iterable[str]], Callable[[CommandSource, dict], Iterable[str]]]
__SOURCE_ERROR_CONTEXT_CALLBACK = Union[Callable[[], Any], Callable[[CommandSource], Any], Callable[[CommandSource, CommandError], Any], Callable[[CommandSource, CommandError, dict], Any]]

RUNS_CALLBACK = __SOURCE_CONTEXT_CALLBACK
ERROR_HANDLER_CALLBACK = __SOURCE_ERROR_CONTEXT_CALLBACK
FAIL_MSG_CALLBACK = __SOURCE_CONTEXT_CALLBACK_MSG
SUGGESTS_CALLBACK = __SOURCE_CONTEXT_CALLBACK_STR_ITERABLE
REQUIRES_CALLBACK = __SOURCE_CONTEXT_CALLBACK_BOOL


class _ErrorHandler(NamedTuple):
	callback: ERROR_HANDLER_CALLBACK
	handled: bool


_ERROR_HANDLER_TYPE = Dict[Type[CommandError], _ErrorHandler]


class AbstractNode(ABC):
	def __init__(self):
		self._children_literal: Dict[str, List[Literal]] = collections.defaultdict(list)  # mapping from literal text to related Literal nodes
		self._children: List[AbstractNode] = []
		self._callback: Optional[RUNS_CALLBACK] = None
		self._error_handlers: _ERROR_HANDLER_TYPE = {}
		self._child_error_handlers: _ERROR_HANDLER_TYPE = {}
		self._requirement: REQUIRES_CALLBACK = lambda source: True
		self._requirement_failure_message_getter: Optional[FAIL_MSG_CALLBACK] = None
		self._redirect_node: Optional[AbstractNode] = None
		self._suggestion_getter: SUGGESTS_CALLBACK = lambda: []

	# --------------
	#   Interfaces
	# --------------

	def then(self, node: 'AbstractNode') -> 'AbstractNode':
		"""
		Add a child node to this node
		:param node: a child node for new level command
		"""
		if self._redirect_node is not None:
			raise IllegalNodeOperation('Redirected node is not allowed to add child nodes')
		if isinstance(node, Literal):
			for literal in node.literals:
				self._children_literal[literal].append(node)
		else:
			self._children.append(node)
		return self

	def runs(self, func: RUNS_CALLBACK) -> 'AbstractNode':
		"""
		Executes the given function if the command string ends here
		:param func: A function to execute at this node which accepts maximum 2 parameters (command source and context)
		:rtype: AbstractNode
		"""
		self._callback = func
		return self

	def requires(self, requirement: REQUIRES_CALLBACK, failure_message_getter: Optional[FAIL_MSG_CALLBACK] = None) -> 'AbstractNode':
		"""
		Set the requirement for the command source to enter this node
		:param requirement: A callable function which accepts maximum 2 parameters (command source and context)
		and return a bool indicating whether the source is allowed to executes this command or not
		:param failure_message_getter: The reason to show in the exception when the requirement is not met.
		It's a callable function which accepts maximum 2 parameters (command source and context). If it's not specified,
		a default message will be used
		:rtype: AbstractNode
		"""
		self._requirement = requirement
		self._requirement_failure_message_getter = failure_message_getter
		return self

	def redirects(self, redirect_node: 'AbstractNode') -> 'AbstractNode':
		"""
		Redirect the child branches of this node to the child branches of the given node
		:type redirect_node: AbstractNode
		:rtype: AbstractNode
		"""
		if self.has_children():
			raise IllegalNodeOperation('Node with children nodes is not allowed to be redirected')
		self._redirect_node = redirect_node
		return self

	def suggests(self, suggestion: SUGGESTS_CALLBACK) -> 'AbstractNode':
		"""
		Set the provider for command suggestions of this node
		:param suggestion: A callable function which accepts maximum 2 parameters (command source and context)
		and return an iterable of str indicating the current command suggestions
		:rtype: AbstractNode
		"""
		self._suggestion_getter = suggestion
		return self

	def on_error(self, error_type: Type[CommandError], handler: ERROR_HANDLER_CALLBACK, *, handled: bool = False) -> 'AbstractNode':
		"""
		When a command error occurs, invoke the handler
		:param error_type: A class that is subclass of CommandError
		:param handler: A callback function which accepts maximum 3 parameters (command source, error and context)
		:param handled: If handled is set to True, error.set_handled() is called automatically when invoking the handler callback
		"""
		if not issubclass(error_type, CommandError):
			raise TypeError('error_type parameter should be a class inherited from CommandError, but class {} found'.format(error_type))
		self._error_handlers[error_type] = _ErrorHandler(handler, handled)
		return self

	def on_child_error(self, error_type: Type[CommandError], handler: ERROR_HANDLER_CALLBACK, *, handled: bool = False) -> 'AbstractNode':
		"""
		When receives a command error from one of the node's child, invoke the handler
		:param error_type: A class that is subclass of CommandError
		:param handler: A callback function which accepts maximum 3 parameters (command source, error and context)
		:param handled: If handled is set to True, error.set_handled() is called automatically when invoking the handler callback
		"""
		if not issubclass(error_type, CommandError):
			raise TypeError('error_type parameter should be a class inherited from CommandError, but class {} found'.format(error_type))
		self._child_error_handlers[error_type] = _ErrorHandler(handler, handled)
		return self

	def print_tree(self, line_writer: tree_printer.LineWriter = print):
		def make_tree(cmd_node: AbstractNode) -> tree_printer.Node:
			node = tree_printer.Node(str(cmd_node))
			for child in cmd_node.get_children():
				node.add_child(make_tree(child))
			return node
		tree_printer.print_tree(make_tree(self), line_writer)

	# -------------------
	#   Interfaces ends
	# -------------------

	def _get_usage(self) -> str:
		raise NotImplementedError()

	def has_children(self):
		return len(self._children) + len(self._children_literal) > 0

	def get_children(self) -> List['AbstractNode']:
		children = []
		for literal_list in self._children_literal.values():
			children.extend(literal_list)
		children.extend(self._children)
		return misc_util.unique_list(children)

	def parse(self, text: str) -> ParseResult:
		"""
		Try to parse the text and get a argument. Return a ParseResult instance indicating the parsing result
		ParseResult.value: The value to store in the context dict
		ParseResult.remaining: The remain
		:param str text: the remaining text to be parsed. It's supposed to not be started with DIVIDER character
		"""
		raise NotImplementedError()

	@staticmethod
	def __smart_callback(callback: Callable, *args):
		sig = inspect.signature(callback)
		spec_args = inspect.getfullargspec(callback).args
		spec_args_len = len(spec_args)
		if isinstance(callback, MethodType):  # class method, remove the 1st param
			spec_args_len -= 1
		try:
			sig.bind(*args[:spec_args_len])  # test if using full arg length is ok
		except TypeError:
			raise

		# make sure all passed CommandContext are copies
		args = list(args)
		for i in range(len(args)):
			if isinstance(args[i], CommandContext):
				args[i] = args[i].copy()

		return callback(*args[:spec_args_len])

	def __handle_error(self, error: CommandError, context: CommandContext, error_handlers: _ERROR_HANDLER_TYPE):
		for error_type, handler in error_handlers.items():
			if isinstance(error, error_type):
				self.__smart_callback(handler.callback, context.source, error, context)
				if handler.handled:
					error.set_handled()

	def __raise_error(self, error: CommandError, context: CommandContext):
		self.__handle_error(error, context, self._error_handlers)
		raise error

	def _get_suggestions(self, context: CommandContext) -> Iterable[str]:
		return self.__smart_callback(self._suggestion_getter, context.source, context)

	def _execute_command(self, context: CommandContext) -> None:
		command = context.command  # type: str
		try:
			parse_result = self.parse(context.command_remaining)
		except CommandSyntaxError as error:
			error.set_parsed_command(context.command_read)
			error.set_failed_command(context.command_read + context.command_remaining[:error.char_read])
			self.__raise_error(error, context)
		else:
			next_remaining = utils.remove_divider_prefix(context.command_remaining[parse_result.char_read:])  # type: str
			total_read = len(command) - len(next_remaining)  # type: int

			with context.read_command(self, parse_result, total_read):
				if self._requirement is not None:
					if not self.__smart_callback(self._requirement, context.source, context):
						getter = self._requirement_failure_message_getter or (lambda: None)
						failure_message = self.__smart_callback(getter, context.source, context)
						self.__raise_error(RequirementNotMet(context.command_read, context.command_read, failure_message), context)

				# Parsing finished
				if len(next_remaining) == 0:
					callback = self._callback
					if callback is None and self._redirect_node is not None:
						callback = self._redirect_node._callback
					if callback is not None:
						self.__smart_callback(callback, context.source, context)
					else:
						self.__raise_error(UnknownCommand(context.command_read, context.command_read), context)
				# Un-parsed command string remains
				else:
					# Redirecting
					node = self if self._redirect_node is None else self._redirect_node

					argument_unknown = False
					# No child at all
					if not node.has_children():
						argument_unknown = True
					else:
						# Pass the remaining command string to the children
						next_literal = utils.get_element(next_remaining)
						try:
							# Check literal children first
							literal_error = None
							for child_literal in node._children_literal.get(next_literal, []):
								try:
									with context.enter_child(child_literal):
										child_literal._execute_command(context)
									break
								except CommandError as e:
									# it's ok for a direct literal node to fail
									# other literal might still have a chance to consume this command
									literal_error = e
							else:  # All literal children fails
								if literal_error is not None:
									raise literal_error
								for child in node._children:
									with context.enter_child(child):
										child._execute_command(context)
									break
								else:  # No argument child
									argument_unknown = True

						except CommandError as error:
							self.__handle_error(error, context, self._child_error_handlers)
							raise error from None

					if argument_unknown:
						self.__raise_error(UnknownArgument(context.command_read, command), context)

	def _generate_suggestions(self, context: CommandContext) -> CommandSuggestions:
		"""
		Return a list of tuple (suggested command, suggested argument)
		"""
		def self_suggestions():
			return CommandSuggestions([CommandSuggestion(command_read_at_the_beginning, s) for s in self._get_suggestions(context)])

		suggestions = CommandSuggestions()
		# [!!aa bb cc] dd
		# read         suggested
		command_read_at_the_beginning = context.command_read
		if len(context.command_remaining) == 0:
			return self_suggestions()
		try:
			result = self.parse(context.command_remaining)
		except CommandSyntaxError:
			return self_suggestions()
		else:
			success_read = len(context.command) - len(context.command_remaining) + result.char_read  # type: int
			next_remaining = utils.remove_divider_prefix(context.command_remaining[result.char_read:])  # type: str
			total_read = len(context.command) - len(next_remaining)  # type: int

			with context.read_command(self, result, total_read):
				if self._requirement is not None and not self.__smart_callback(self._requirement, context.source, context):
					return CommandSuggestions()

				# Parsing finished
				if len(next_remaining) == 0:
					# total_read == success_read means DIVIDER does not exists at the end of the input string
					# in that case, ends at this current node
					if success_read == total_read:
						return self_suggestions()

				node = self if self._redirect_node is None else self._redirect_node
				# Check literal children first
				children_literal = node._children_literal.get(utils.get_element(next_remaining), [])
				for child_literal in children_literal:
					with context.enter_child(child_literal):
						suggestions.extend(child_literal._generate_suggestions(context))
				if len(children_literal) == 0:
					for literal_list in node._children_literal.values():
						for child_literal in literal_list:
							with context.enter_child(child_literal):
								suggestions.extend(child_literal._generate_suggestions(context))
					usages = []
					for child in node._children:
						with context.enter_child(child):
							suggestions.extend(child._generate_suggestions(context))
							if len(next_remaining) == 0:
								usages.append(child._get_usage())
					if len(next_remaining) == 0:
						suggestions.complete_hint = '|'.join(usages)
		return suggestions


class EntryNode(AbstractNode, ABC):
	def execute(self, source, command):
		"""
		Parse and execute this command
		Raise variable CommandError if parsing fails
		:param CommandSource source: the source that executes this command
		:param str command: the command string to execute
		"""
		try:
			context = CommandContext(source, command)
			with context.enter_child(self):
				self._execute_command(context)
		except LiteralNotMatch as error:
			# the root literal node fails to parse the first element
			raise UnknownRootArgument(error.get_parsed_command(), error.get_failed_command()) from error

	def generate_suggestions(self, source, command) -> CommandSuggestions:
		"""
		Get a list of command suggestion of given command
		Return an empty list if parsing fails
		:param CommandSource source: the source that executes this command
		:param str command: the command string to execute
		"""
		context = CommandContext(source, command)
		with context.enter_child(self):
			return self._generate_suggestions(context)


class Literal(EntryNode):
	"""
	A literal argument, doesn't store any value, only for extending and readability of the command
	The only argument type that is allowed to use the execute method
	"""
	def __init__(self, literal: str or Iterable[str]):
		super().__init__()
		if isinstance(literal, str):
			literals = {literal}
		elif isinstance(literal, Iterable):
			literals = set(literal)
		else:
			raise TypeError('Only str or Iterable[str] is accepted')
		for literal in literals:
			if not isinstance(literal, str):
				raise TypeError('Literal node only accepts str but {} found'.format(type(literal)))
			if utils.DIVIDER in literal:
				raise TypeError('DIVIDER character "{}" cannot be inside a literal'.format(utils.DIVIDER))
		self.literals = literals  # type: Set[str]
		self._suggestion_getter = lambda: self.literals

	def _get_usage(self) -> str:
		return '|'.join(sorted(self.literals))

	def suggests(self, suggestion: SUGGESTS_CALLBACK) -> 'AbstractNode':
		raise IllegalNodeOperation('Literal node doe not support suggests')

	def parse(self, text):
		arg = utils.get_element(text)
		if arg in self.literals:
			return ParseResult(None, len(arg))
		else:
			raise LiteralNotMatch('Invalid Argument', len(arg))

	def __str__(self):
		import json
		return 'Literal {}'.format(json.dumps(tuple(self.literals)[0]) if len(self.literals) == 1 else set(self.literals))

	def __repr__(self):
		return 'Literal[literals={}]'.format(self.literals)


class ArgumentNode(AbstractNode, ABC):
	def __init__(self, name: str):
		super().__init__()
		self.__name = name

	def get_name(self) -> str:
		return self.__name

	def _get_usage(self) -> str:
		return '<{}>'.format(self.__name)

	def __str__(self):
		return '{} <{}>'.format(self.__class__.__name__, self.get_name())

	def __repr__(self):
		return '{}[name={}]'.format(self.__class__.__name__, self.__name)

