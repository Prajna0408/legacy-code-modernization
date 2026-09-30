from __future__ import annotations
import hashlib
import re
from pathlib import Path
from typing import Any, Iterable
from tree_sitter import Language, Parser
import tree_sitter_java
try: import tree_sitter_c
except Exception: tree_sitter_c = None
try: import tree_sitter_cpp
except Exception: tree_sitter_cpp = None
try: import tree_sitter_python
except Exception: tree_sitter_python = None
try: import tree_sitter_javascript
except Exception: tree_sitter_javascript = None
try: import tree_sitter_typescript
except Exception: tree_sitter_typescript = None

EXTENSIONS={'.java':'java','.c':'c','.h':'c','.cpp':'cpp','.cc':'cpp','.hpp':'cpp','.py':'python','.js':'javascript','.mjs':'javascript','.ts':'typescript','.tsx':'tsx','.cbl':'cobol','.cob':'cobol','.cpy':'cobol'}
CLASS_NODES={'class_declaration','class_definition','interface_declaration','enum_declaration','record_declaration','struct_specifier','namespace_definition'}
METHOD_NODES={'method_declaration','constructor_declaration','function_definition','function_declaration','method_definition','function_item'}
CONTROL_NODES={'if_statement','if_expression','for_statement','for_in_statement','while_statement','do_statement','switch_expression','switch_statement','try_statement','catch_clause','finally_clause','conditional_expression'}
TOKEN_RE = re.compile(
    r"""
    //[^\n]*
    |/\*.*?\*/
    |#[^\n]*
    |--[^\n]*
    |"(?:\\.|[^"\\])*"
    |'(?:\\.|[^'\\])*'
    |\b\d+(?:\.\d+)?\b
    |[A-Za-z_$][A-Za-z0-9_$-]*
    |==|!=|<=|>=|&&|\|\||->|=>|::
    |[+\-*/%<>=!&|]
    |[{}()\[\];,.:]
    |\s+
    |.
    """,
    re.VERBOSE | re.DOTALL
)

# This function detects the programming language of a source file based on its file extension. It uses a predefined mapping of file extensions to language names. If the file extension is not recognized, it returns 'unknown'.
def detect_language(path:str)->str:
    return EXTENSIONS.get(Path(path).suffix.lower(),'unknown')


# This function returns a tree-sitter Language object for the specified programming language. It supports Java, C, C++, Python, JavaScript, TypeScript, and TSX. If the language is not supported or if there is an error loading the grammar, it returns None.
def _language(language:str):
    if language=='java': 
        return Language(tree_sitter_java.language())
    grammar={'c':tree_sitter_c,'cpp':tree_sitter_cpp,'python':tree_sitter_python,'javascript':tree_sitter_javascript,'typescript':tree_sitter_typescript,'tsx':tree_sitter_typescript}.get(language)
    if grammar is None:
        return None
    try:
        return Language(grammar.language())
    except Exception:
        return None


# This function performs lexical analysis on the source code. It uses a regular expression to tokenize the source code into different kinds of tokens, such as comments, strings, numbers, identifiers, operators, and punctuation. It counts the occurrences of each token kind and records their positions in the source code. The function returns a dictionary containing the total token count, counts of each token kind, and a list of token information.
def lexical_analysis(source:str)->dict[str,Any]:
    tokens = []  #list to hold token information
    counts = {}  #dictionary to hold counts of each token kind

    for match in TOKEN_RE.finditer(source):  # iterate over all matches of the token regex in the source code
        text = match.group(0)

        if text.isspace(): # skip whitespace tokens
            continue

        if text.startswith("//") or text.startswith("/*") or text.startswith("#") or text.startswith("--"):
            kind = "comment"
        elif text.startswith('"') or text.startswith("'"):
            kind = "string"
        elif re.fullmatch(r"\d+(?:\.\d+)?", text):
            kind = "number"
        elif re.fullmatch(r"[A-Za-z_$][A-Za-z0-9_$-]*", text):
            kind = "identifier"
        elif re.fullmatch(r"[+\-*/%<>=!&|]+|==|!=|<=|>=|&&|\|\||->|=>|::", text):
            kind = "operator"
        elif text in "{}()[];,.:":
            kind = "punctuation"
        else:
            kind = "other"

        counts[kind] = counts.get(kind, 0) + 1

        pos = match.start()
        line = source.count("\n", 0, pos) + 1  #line number where the token starts (1-based) 
        previous_newline = source.rfind("\n", 0, pos) #position of the previous newline character before the token (0-based)
        column = pos if previous_newline < 0 else pos - previous_newline - 1 

        tokens.append(
            {
                "kind": kind,
                "text": text[:200], 
                "line": line,
                "column": column,
            }
        )
    return {'token_count':len(tokens),'counts':counts,'tokens':tokens}


# This function generates a unique identifier for a given AST node based on its position in the source code and its type. It constructs a key string that includes the file path, start and end positions of the node, and the node type. The key is then hashed using SHA-1, and the first 16 characters of the hexadecimal digest are returned as the unique identifier prefixed with 'ast_'.
def _node_id(path:str,node:Any)->str:
    key=f'{path}:{node.start_point[0]+1}:{node.start_point[1]}:{node.end_point[0]+1}:{node.end_point[1]}:{node.type}'
    return 'ast_'+hashlib.sha1(key.encode()).hexdigest()[:16]

# This function recursively constructs a dictionary representation of an AST node and its children. It includes information such as the node's unique identifier, type, whether it is named, start and end positions, and any errors. If the node has children, it recursively processes them up to a specified maximum depth. If the maximum depth is exceeded, it marks the node as truncated. For leaf nodes, it includes the text content of the node.
def _ast(node:Any,source:bytes,path:str,depth=0,max_depth=40):
    out={
         'id':_node_id(path,node),
         'type':node.type,
         'named':bool(node.is_named),
         'start':[
                  node.start_point[0]+1,
                  node.start_point[1]
                ],
         'end':[
                 node.end_point[0]+1,
                 node.end_point[1]
                ]
        }
    if getattr(node,'has_error',False):
        out['has_error']=True
    if depth>=max_depth:
        out['truncated']=True; return out
    if node.child_count==0:
        out['text']=source[node.start_byte:node.end_byte].decode('utf-8','replace')[:500]
    else:
        out['children']=[_ast(c,source,path,depth+1,max_depth) for c in node.children if c.is_named]
    return out

# This function performs a depth-first traversal of the AST, yielding each node in the tree. It starts with the given node and recursively visits its children, yielding them in order. This allows for easy iteration over all nodes in the AST. Generator function that yields the current node and then recursively yields all child nodes.
def _walk(node:Any)->Iterable[Any]:
    yield node
    for c in node.children:
        yield from _walk(c)


# This function extracts the text content of a given AST node from the source code. It uses the node's start and end byte positions to slice the source bytes and then decodes the slice into a UTF-8 string, replacing any invalid characters. This allows for retrieving the exact text represented by the AST node.
def _text(node:Any,source:bytes)->str:
    return source[node.start_byte:node.end_byte].decode('utf-8','replace')

# This function retrieves the first identifier found among the children of a given AST node. It checks for various types of identifiers, such as regular identifiers, type identifiers, field identifiers, and property identifiers. If an identifier is found, it returns its text content; otherwise, it returns None.
def _first_identifier(node:Any,source:bytes):
    for c in node.children:
        if c.type in {'identifier','type_identifier','field_identifier','property_identifier'}:
            return _text(c,source)
    return None


# This function extracts import statements from the AST of a source file. It traverses the AST and collects the text of nodes that represent import declarations, import statements, import specifications, using directives, or preprocessor includes. The extracted imports are returned as a sorted list of unique strings. 
def _extract_imports(root,source:bytes):
    return sorted({_text(n,source).strip() for n in _walk(root) if n.type in {'import_declaration','import_statement','import_specification','using_directive','preproc_include'} and _text(n,source).strip()})

# This function extracts symbols (classes, methods, and calls) from the AST of a source file. It traverses the AST and collects information about class declarations, method declarations, and function/method calls. For each class and method, it records the name, unique node identifier, and source code range. For calls, it collects the names of the called functions or methods. The extracted symbols are returned as three separate lists: classes, methods, and calls.
def _extract_symbols(root,source:bytes):
    classes=[];methods=[];calls=[]
    for n in _walk(root):
        if n.type in CLASS_NODES:
            name=_first_identifier(n,source)
            if name:
                classes.append({'name':name,'node_id':_node_id('<source>',n),'range':{'start':[n.start_point[0]+1,n.start_point[1]],'end':[n.end_point[0]+1,n.end_point[1]]}})
        if n.type in METHOD_NODES:
            name=_first_identifier(n,source)
            if name:
                methods.append({'name':name,'node_id':_node_id('<source>',n),'range':{'start':[n.start_point[0]+1,n.start_point[1]],'end':[n.end_point[0]+1,n.end_point[1]]}})
        if n.type in {'method_invocation','call_expression','function_call','call','invocation_expression'}:
            ids=[_text(c,source) for c in n.children if c.type in {'identifier','property_identifier','field_identifier'}]
            if ids:
                calls.append(ids[-1])
    return classes,methods,sorted(set(calls))


# This function performs a generic analysis of the source code to extract class names, method names, and function/method calls using regular expressions. It searches for patterns that match class/interface/struct/enum declarations, function/method definitions, and calls to functions or methods. The results are returned as a dictionary containing sorted lists of unique class names, method names, and call names.
def _generic_analysis(source:str):
    return {'classes':sorted(set(re.findall(r'\b(?:class|interface|struct|enum)\s+([A-Za-z_$][\w$]*)',source,re.I))),
            'methods':sorted(set(re.findall(r'\b(?:def|function|procedure|perform)\s+([A-Za-z_$][\w$-]*)',source,re.I))),
            'calls':sorted(set(re.findall(r'\b(?:PERFORM|CALL)\s+([A-Z0-9_$][A-Z0-9_$-]*)',source,re.I)))}

# This function creates a slice representation of a given AST node. It generates a unique slice identifier based on the node's position and type, and includes metadata such as the kind of slice (e.g., type declaration, callable, control flow), the name of the symbol (if applicable), the grammar node type, start and end positions, the corresponding AST node identifier, and the text content of the node. The resulting slice is returned as a dictionary.
def _make_slice(node,source:bytes,path:str,kind:str,name=None):
    aid=_node_id(path,node);return {'slice_id':aid.replace('ast_','slice_'),'kind':kind,'name':name,'grammar_node':node.type,'start':[node.start_point[0]+1,node.start_point[1]],'end':[node.end_point[0]+1,node.end_point[1]],'ast_node_id':aid,'text':_text(node,source)}

# This function generates grammar slices from the AST of a source file. It traverses the AST and creates slices for class declarations, method declarations, and control flow statements. Each slice includes metadata such as the kind of slice, the name of the symbol (if applicable), the grammar node type, start and end positions, the corresponding AST node identifier, and the text content of the node. The resulting slices are sorted by their start and end positions in the source code and returned as a list.
def _grammar_slices(root,source:bytes,path:str):
    out=[]
    for n in _walk(root):
        if n.type in CLASS_NODES:out.append(_make_slice(n,source,path,'type_declaration',_first_identifier(n,source)))
        elif n.type in METHOD_NODES:out.append(_make_slice(n,source,path,'callable',_first_identifier(n,source)))
        elif n.type in CONTROL_NODES:out.append(_make_slice(n,source,path,'control_flow'))
    return sorted(out,key=lambda x:(x['start'][0],x['start'][1],x['end'][0],x['end'][1])) # sort slices by start and end positions in the source code

#  This function generates generic slices from the source code when a specific grammar is not available. It identifies structural blocks in the source code, such as class, interface, struct, enum, function, and procedure definitions, using regular expressions. For each identified block, it creates a slice with metadata including a unique slice identifier, the kind of slice (structural fallback), the grammar node type (generic structural block), start and end positions, and the text content of the block. If no structural blocks are found, it creates a single slice representing the entire source unit. The resulting slices are returned as a list.
def _generic_slices(source:str,path:str):
    lines=source.splitlines()
    starts=[i for i,line in enumerate(lines) if re.search(r'(?im)^\s*(?:class|interface|struct|enum|def|function|procedure)\b',line)]
    if not starts:return [{'slice_id':'slice_'+hashlib.sha1(path.encode()).hexdigest()[:16],'kind':'source_unit','name':Path(path).stem,'grammar_node':'generic_source','start':[1,0],'end':[len(lines),0],'ast_node_id':None,'text':source}]
    out=[]
    for i,start in enumerate(starts):
        end=starts[i+1] if i+1<len(starts) else len(lines);text='\n'.join(lines[start:end]).strip()
        if text:
            key=f'{path}:{start+1}:{end}';out.append({'slice_id':'slice_'+hashlib.sha1(key.encode()).hexdigest()[:16],'kind':'structural_fallback','name':None,'grammar_node':'generic_structural_block','start':[start+1,0],'end':[end,0],'ast_node_id':None,'text':text})
    return out


# This function resolves dependencies between source files based on class references, imports, and method calls. It constructs a dependency graph by analyzing the symbols in each file and identifying relationships with other files. The function returns a dictionary containing the nodes (file paths), edges (dependencies with evidence), and a matrix representing the presence of dependencies between files.
def _resolve_dependencies(files):
    paths=[f['path'] for f in files];class_to_file={};method_to_files={}
    for f in files:
        for c in f['symbols']['classes']:class_to_file.setdefault(c['name'],f['path'])
        for m in f['symbols']['methods']:method_to_files.setdefault(m['name'],set()).add(f['path'])
    edges=[]
    for f in files:
        src=f['path'];text=f['_source_text'];imports=f['imports'];targets={}
        def ensure(t):return targets.setdefault(t,{'evidence':set(),'calls':set()})
        for cls,target in class_to_file.items():
            if target!=src and re.search(rf'\b{re.escape(cls)}\b',text):ensure(target)['evidence'].add('type_reference')
        for target in paths:
            if target!=src and any(Path(target).stem in imp for imp in imports):ensure(target)['evidence'].add('import')
        for call in f['symbols']['calls']:
            candidates=method_to_files.get(call,set())
            if len(candidates)==1:
                target=next(iter(candidates))
                if target!=src:ensure(target)['evidence'].add('unique_method');ensure(target)['calls'].add(call)
        for cls,target in class_to_file.items():
            if target!=src and re.search(rf'\bnew\s+{re.escape(cls)}\s*\(',text):ensure(target)['evidence'].add('constructor')
        for target,data in targets.items():edges.append({'source':src,'target':target,'calls':sorted(data['calls']),'evidence':sorted(data['evidence']),'dependency':True})
    matrix={src:{dst:int(any(e['source']==src and e['target']==dst for e in edges)) for dst in paths} for src in paths}
    if not edges:
        print(
            "[Dependency Analysis] No dependencies detected "
            "between the supplied source files."
        )

    else:
        print(
            f"[Dependency Analysis] Detected {len(edges)} "
            "dependency edge(s)."
        )
    return {'nodes':paths,'edges':edges,'matrix':matrix}


# This function parses a list of source files, performing lexical analysis, AST generation, symbol extraction, and dependency resolution. It takes a list of dictionaries representing source files (each containing a 'path' and 'content') and returns a dictionary containing detailed information about each file, including language detection, parser type, SHA-256 hash, line count, parse errors, lexical analysis results, AST structure, imports, symbols (classes, methods, calls), grammar slices, and a dependency call graph. The function also provides static analysis metrics such as file count, languages used, total tokens, total grammar slices, and dependency edge count.
def parse_sources(source_files:list[dict[str,str]])->dict[str,Any]:
    if not isinstance(source_files,list):raise TypeError('source_files must be a list')
    files=[]
    for item in source_files:
        if 'path' not in item or 'content' not in item:raise ValueError('Each source file requires path and content')
        path=item['path'];content=item['content'];language=detect_language(path);raw=content.encode('utf-8');lexical=lexical_analysis(content);grammar=_language(language)
        if grammar is not None:
            tree=Parser(grammar).parse(raw);root=tree.root_node;ast=_ast(root,raw,path);classes,methods,calls=_extract_symbols(root,raw);imports=_extract_imports(root,raw);slices=_grammar_slices(root,raw,path);parser_kind='tree-sitter';parse_error=bool(root.has_error)
        else:
            info=_generic_analysis(content);ast={'id':'ast_'+hashlib.sha1(path.encode()).hexdigest()[:16],'type':'generic_source','named':True,'start':[1,0],'end':[len(content.splitlines()),0],'children':[{'type':'structural_symbol','name':n} for n in info['classes']+info['methods']]};classes=[{'name':n,'node_id':None,'range':None} for n in info['classes']];methods=[{'name':n,'node_id':None,'range':None} for n in info['methods']];calls=info['calls'];imports=[];slices=_generic_slices(content,path);parser_kind='generic-structural';parse_error=False
        files.append({'path':path,'language':language,'parser':parser_kind,'sha256':hashlib.sha256(raw).hexdigest(),'line_count':len(content.splitlines()),'parse_has_error':parse_error,'lexical_analysis':lexical,'ast':ast,'imports':imports,'symbols':{'classes':classes,'methods':methods,'calls':calls},'grammar_slices':slices,'_source_text':content})
    graph=_resolve_dependencies(files)
    for f in files:f.pop('_source_text',None)
    return {'files':files,'dependency_call_graph':graph,'static_analysis':{'file_count':len(files),'languages':sorted({f['language'] for f in files}),'tree_sitter_files':sum(f['parser']=='tree-sitter' for f in files),'fallback_files':sum(f['parser']!='tree-sitter' for f in files),'total_tokens':sum(f['lexical_analysis']['token_count'] for f in files),'total_grammar_slices':sum(len(f['grammar_slices']) for f in files),'dependency_edge_count':len(graph['edges'])}}

__all__=['detect_language','lexical_analysis','parse_sources']
