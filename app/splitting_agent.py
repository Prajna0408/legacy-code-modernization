from __future__ import annotations

import json
import os
import re
from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Protocol

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    load_dotenv = None

try:
    from openai import AzureOpenAI
except ImportError:  # pragma: no cover
    AzureOpenAI = None

from .state import PipelineState

# this interface defines the LLM client
class JsonLLM(Protocol):
    def chat_json(self, system_prompt: str, user_prompt: str) -> dict[str, Any]: ...

# this is a simple implementation of the LLM client that uses Azure OpenAI
class AzureOpenAIJsonClient:
    def __init__(self) -> None:
        if load_dotenv:
            load_dotenv()
        if AzureOpenAI is None:
            raise RuntimeError("Install the 'openai' package first.")
        self.endpoint = os.getenv("AZURE_OPENAI_ENDPOINT") or os.getenv("azure_endpoint")
        self.key = os.getenv("AZURE_OPENAI_API_KEY") or os.getenv("AZURE_OPENAI_KEY")
        self.version = os.getenv("AZURE_OPENAI_API_VERSION") or os.getenv("api_version") or "2024-12-01-preview"
        self.deployment = os.getenv("AZURE_OPENAI_DEPLOYMENT") or os.getenv("model")
        missing = [n for n,v in (("endpoint",self.endpoint),("api_key",self.key),("deployment",self.deployment)) if not v]
        if missing:
            raise RuntimeError("Missing Azure OpenAI configuration: " + ", ".join(missing))
        self.client = AzureOpenAI(api_version=self.version, azure_endpoint=self.endpoint, api_key=self.key)
        self.timeout = float(os.getenv("AZURE_OPENAI_TIMEOUT_SECONDS", "60"))

# this method sends a request to the Azure OpenAI API and expects a JSON object response
    def chat_json(self, system_prompt: str, user_prompt: str) -> dict[str, Any]:
        print("[Azure] Sending request...")
        r = self.client.chat.completions.create(
            model=self.deployment,
            messages=[{"role":"system","content":system_prompt},{"role":"user","content":user_prompt}],
            temperature=0,
            response_format={"type":"json_object"},
            timeout=self.timeout,
        )
        print("[Azure] Response received.")
        content = r.choices[0].message.content or "{}"
        try:
            obj = json.loads(content)
        except json.JSONDecodeError as e:
            raise RuntimeError("Azure OpenAI returned invalid JSON.") from e
        if not isinstance(obj, dict):
            raise RuntimeError("Azure OpenAI response must be a JSON object.")
        return obj


# this class represents a slice of code extracted from the source files, along with its metadata
@dataclass(frozen=True)
class SliceRecord:
    slice_id: str
    source_file: str
    language: str
    kind: str
    name: str | None
    grammar_node: str | None
    start: list[int]
    end: list[int]
    text: str

# this property extracts identifiers from the slice text, excluding common keywords and reserved words
    @property
    def identifiers(self) -> set[str]:
        stop = {"if","else","for","while","do","switch","case","try","catch","finally","return","new","class","interface","enum","record","struct","public","private","protected","static","final","void","int","long","float","double","boolean","string","true","false","null","this","super"}
        return {x.lower() for x in re.findall(r"[A-Za-z_][A-Za-z0-9_$-]*", self.text) if x.lower() not in stop}


# this class is responsible for orchestrating the splitting of code into logical modules and contracts
class SplittingAgent:
    STAGE = "splitting_agent"

    def __init__(self, llm: JsonLLM | None = None, max_llm_slices: int = 40, max_contract_clusters: int = 8):
        self._llm = llm
        self.max_llm_slices = max_llm_slices
        self.max_contract_clusters = max_contract_clusters

# this method runs the splitting agent on the given pipeline state, reading the parser output and writing the splitting input and output artifacts
    def run(self, state: PipelineState) -> PipelineState:
        parser_output = state.read_artifact("parser_output")
        splitting_input = self.build_splitting_input(parser_output)
        state.write_artifact("splitting_input", splitting_input, stage=self.STAGE)
        result = self.process(splitting_input)
        state.write_artifact("splitting_output", result, stage=self.STAGE)
        return state

# this static method builds the input for the splitting agent from the parser output, extracting relevant information from the parsed files and the dependency call graph
    @staticmethod
    def build_splitting_input(parser_output: dict[str, Any]) -> dict[str, Any]:
        return {
            "files": [
                {
                    "path": f.get("path", ""),
                    "language": f.get("language", "unknown"),
                    "grammar_slices": f.get("grammar_slices", []),
                    "symbols": f.get("symbols", {}),
                    "imports": f.get("imports", []),
                }
                for f in parser_output.get("files", [])
            ],
            "dependency_call_graph": parser_output.get("dependency_call_graph", {"nodes": [], "edges": [], "matrix": {}}),
        }

# this method processes the splitting input, performing plumbing cleanup, slice collection, execution path building, logical grouping, semantic clustering, contract synthesis, and module dependency building. It returns a dictionary containing the resulting modules, execution paths, module dependencies, dependency traceability statistics, and other relevant statistics.
    def process(self, inp: dict[str, Any]) -> dict[str, Any]:
        files = [self._clean_plumbing(f) for f in inp.get("files", [])]
        slices = self._collect_slices(files)
        graph = inp.get("dependency_call_graph", {}) or {}
        paths = self._build_execution_paths(files, graph)
        groups = self._build_logical_groups(slices, paths)
        print(f"[Splitting] Logical execution groups: {len(groups)} from {len(slices)} grammar slices.")
        if not graph.get("edges"):
            print("[Splitting Agent] No dependency edges were provided by the Parser. Processing files as independent execution units.")
        clusters = self._semantic_cluster(groups)
        modules = self._synthesize_contracts(clusters)
        deps = self._build_module_dependencies(modules, graph, slices)
        mapped = self._count_mapped_edges(deps, modules, graph)
        return {
            "modules": modules,
            "execution_paths": paths,
            "module_dependencies": deps,
            "dependency_traceability": {
                "parser_edge_count": len(graph.get("edges", []) or []),
                "mapped_parser_edge_count": mapped,
                "unmapped_parser_edge_count": max(0, len(graph.get("edges", []) or []) - mapped),
            },
            "statistics": {
                "file_count": len(files),
                "slice_count": len(slices),
                "logical_execution_group_count": len(groups),
                "execution_path_count": len(paths),
                "cluster_count": len(clusters),
                "module_count": len(modules),
                "module_dependency_count": len(deps),
                "plumbing_items_removed": sum(len(f.get("stripped_plumbing", [])) for f in files),
            },
        }

# this method cleans up plumbing code from the grammar slices of a file, removing common logging and print statements, as well as certain OPEN INPUT/OUTPUT/EXTEND directives. It returns a new file dictionary with the cleaned grammar slices and a list of stripped plumbing items.
    def _clean_plumbing(self, f: dict[str, Any]) -> dict[str, Any]:
        pats = [
            re.compile(r"\bSystem\s*\.\s*out\s*\.\s*println\s*\([^;]*\)\s*;?", re.I),
            re.compile(r"\b(?:logger|log)\s*\.\s*(?:debug|info|warn|error|trace)\s*\([^;]*\)\s*;?", re.I),
            re.compile(r"(?im)^\s*OPEN\s+INPUT\b.*$"),
            re.compile(r"(?im)^\s*OPEN\s+(?:OUTPUT|I-O|EXTEND)\b.*$"),
        ]
        findings = {}
        for s in f.get("grammar_slices", []):
            text = str(s.get("text", ""))
            for p in pats:
                for m in p.finditer(text):
                    t = " ".join(m.group(0).split())
                    if t:
                        findings[t] = {"text": t, "line": s.get("start", [0,0])[0]}
        cleaned = []
        for s in f.get("grammar_slices", []):
            x = dict(s); text = str(x.get("text", ""))
            for item in findings.values(): text = text.replace(item["text"], "")
            x["text"] = text.strip(); cleaned.append(x)
        return {**f, "grammar_slices": cleaned, "stripped_plumbing": list(findings.values())}


# this method collects all grammar slices from the parsed files and creates a list of SliceRecord objects, which contain metadata about each slice, such as its ID, source file, language, kind, name, grammar node, start and end positions, and text.
    def _collect_slices(self, files: list[dict[str, Any]]) -> list[SliceRecord]:
        out = []
        for f in files:
            for s in f.get("grammar_slices", []):
                st, en = s.get("start", [0,0]), s.get("end", [0,0])
                out.append(SliceRecord(
                    slice_id=str(s.get("slice_id") or s.get("ast_node_id") or f"{f.get('path')}:{st}:{en}"),
                    source_file=str(f.get("path", "")),
                    language=str(f.get("language", "unknown")),
                    kind=str(s.get("kind", "unknown")),
                    name=str(s["name"]) if s.get("name") is not None else None,
                    grammar_node=str(s["grammar_node"]) if s.get("grammar_node") is not None else None,
                    start=[int(st[0]),int(st[1])], end=[int(en[0]),int(en[1])], text=str(s.get("text", ""))
                ))
        return out


# this method builds execution paths from the dependency call graph, performing a depth-first search to find all paths from each node to its reachable targets. It returns a list of execution path dictionaries, each containing the root node, the list of files in the path, and the depth of the path.
    def _build_execution_paths(self, files, graph):
        adj = defaultdict(set)
        for e in graph.get("edges", []) or []:
            a,b=e.get("source"),e.get("target")
            if a and b and a != b: adj[str(a)].add(str(b))
        nodes={str(f.get("path","")) for f in files}
        nodes.update(str(n) for n in graph.get("nodes", []))
        paths=[]; seen=set()
        def dfs(root, cur, path, visited):
            targets=sorted(adj.get(cur,set()))
            progressed=False
            for t in targets:
                if t in visited: continue
                progressed=True; dfs(root,t,path+[t],visited|{t})
            if not progressed and tuple(path) not in seen:
                seen.add(tuple(path)); paths.append({"root":root,"files":path,"depth":len(path)-1})
        for n in sorted(nodes): dfs(n,n,[n],{n})
        return paths

#this method builds logical groups of slices based on their execution paths and shared identifiers, names, or source files. It returns a list of logical group dictionaries, each containing a group ID, the list of files in the group, and the list of slices in the group.
    def _build_logical_groups(self, slices, paths):
        by_file=defaultdict(list)
        for s in slices: by_file[s.source_file].append(s)
        assigned=set(); groups=[]
        for i,p in enumerate(paths,1):
            items=[]
            for f in p.get("files",[]): items.extend(by_file.get(str(f),[]))
            items=self._dedupe(items)
            for j,sub in enumerate(self._components(items),1):
                if sub:
                    groups.append({"group_id":f"exec_{i}_{j}","files":sorted({s.source_file for s in sub}),"slices":sub})
                    assigned.update(s.slice_id for s in sub)
        remaining=self._dedupe([s for s in slices if s.slice_id not in assigned])
        for i,sub in enumerate(self._components(remaining),1):
            if sub: groups.append({"group_id":f"standalone_{i}","files":sorted({s.source_file for s in sub}),"slices":sub})
        return groups

# this method finds connected components of slices based on shared identifiers, names, or source files. It uses a union-find data structure to group slices together and returns a list of deduplicated slice lists for each component.
    def _components(self, items):
        if not items: return []
        parent=list(range(len(items)))
        # union-find helper functions to find the root of a slice and to union two slices together
        def find(i):
            while parent[i]!=i:
                parent[i]=parent[parent[i]]; i=parent[i]
            return i
        def union(a,b):
            a,b=find(a),find(b)
            if a!=b: parent[b]=a
        for i in range(len(items)):
            for j in range(i+1,len(items)):
                a,b=items[i],items[j]
                same_file=a.source_file==b.source_file
                shared=len(a.identifiers & b.identifiers)
                named=(a.name and b.name and (re.search(rf"\b{re.escape(a.name)}\b", b.text) or re.search(rf"\b{re.escape(b.name)}\b", a.text)))
                if same_file or named or shared>=1: union(i,j)
        comps=defaultdict(list)
        for i,s in enumerate(items): comps[find(i)].append(s)
        return [self._dedupe(v) for v in comps.values()]

# this static method removes duplicates, a list of slices by their slice ID, keeping only the last occurrence of each slice and sorting them by source file and start/end positions. It returns a sorted list of unique slices.
    @staticmethod
    def _dedupe(items):
        return sorted({s.slice_id:s for s in items}.values(), key=lambda s:(s.source_file,s.start[0],s.start[1],s.end[0],s.end[1]))

# this method performs semantic clustering of logical groups of slices using the LLM client. It sends batches of slices to the LLM for clustering and returns a list of cluster dictionaries, each containing the execution group ID, domain context, rationale, and the list of slices in the cluster. It also merges clusters with the same domain context within the same logical group to avoid duplicates.
    def _semantic_cluster(self, groups):
        if not groups: return []
        llm=self._llm or AzureOpenAIJsonClient(); out=[]
        for gi,g in enumerate(groups,1):
            items=g["slices"]
            print(f"[Splitting] Semantic clustering logical group {gi}/{len(groups)} ({len(items)} slices)...")
            # A logical group is split only at a request-size boundary. Each batch
            # carries the same execution-group context; returned labels can be merged later.
            for start in range(0,len(items),self.max_llm_slices):
                batch=items[start:start+self.max_llm_slices]
                payload={"execution_group_id":g["group_id"],"execution_group_files":g["files"],"slices":[{"slice_id":s.slice_id,"source_file":s.source_file,"language":s.language,"kind":s.kind,"name":s.name,"start":s.start,"end":s.end,"text":s.text} for s in batch]}
                r=llm.chat_json(
                    """You are the Domain-Driven Semantic Clustering stage. Group the supplied slices into a SMALL number of coherent business/domain bounded contexts. These slices already belong to one logical execution group. Do not invent domains, dependencies, or behavior. Prefer meaningful business capabilities over one module per method. Every slice_id must appear exactly once. Return JSON only with {\"clusters\":[{\"cluster_id\":\"...\",\"domain_context\":\"...\",\"slice_ids\":[...],\"rationale\":\"...\"}]}""",
                    json.dumps(payload,indent=2)
                )
                by={s.slice_id:s for s in batch}; used=set()
                for c in r.get("clusters",[]) or []:
                    if not isinstance(c,dict): continue
                    sel=[by[str(x)] for x in c.get("slice_ids",[]) if str(x) in by]
                    if sel:
                        used.update(s.slice_id for s in sel)
                        out.append({"execution_group_id":g["group_id"],"domain_context":str(c.get("domain_context","Unspecified")),"rationale":str(c.get("rationale","")),"slices":sel})
                for s in batch:
                    if s.slice_id not in used:
                        out.append({"execution_group_id":g["group_id"],"domain_context":"Unspecified","rationale":"No semantic assignment returned.","slices":[s]})
        # Merge same-domain clusters within the same logical group, preventing
        # arbitrary request batching from creating many duplicate modules.
        merged={}
        for c in out:
            d=re.sub(r"[^a-z0-9]+","",c["domain_context"].lower()) or "unspecified"
            key=(c["execution_group_id"],d)
            if key not in merged: merged[key]={**c,"slices":[]}
            merged[key]["slices"].extend(c["slices"])
        for c in merged.values(): c["slices"]=self._dedupe(c["slices"])
        return list(merged.values())


# this method synthesizes technology-agnostic microservice/domain contracts for each semantic cluster using the LLM client. It sends batches of clusters to the LLM for contract synthesis and returns a list of module dictionaries, each containing the module name, domain context, stripped plumbing items, input and output contracts, business rules, source slices, source files, and execution group ID. It also handles cases where the LLM does not return a response for a cluster by creating a default module with an empty contract.
    def _synthesize_contracts(self, clusters):
        if not clusters: return []
        llm=self._llm or AzureOpenAIJsonClient(); modules=[]
        for start in range(0,len(clusters),self.max_contract_clusters):
            batch=clusters[start:start+self.max_contract_clusters]
            print(f"[Splitting] Synthesizing contract batch {start+1}-{start+len(batch)} of {len(clusters)}...")
            payload={"clusters":[{"cluster_key":f"{c['execution_group_id']}:{i}","domain_context":c["domain_context"],"rationale":c["rationale"],"slices":[{"slice_id":s.slice_id,"source_file":s.source_file,"kind":s.kind,"name":s.name,"start":s.start,"end":s.end,"text":s.text} for s in c["slices"]]} for i,c in enumerate(batch,start=start+1)]}
            r=llm.chat_json(
                """You are the Data Contract Synthesis stage. For each supplied semantic cluster create one technology-agnostic microservice/domain contract. Do not invent behavior. Capture only evidence-supported inputs, outputs and business rules. Return JSON only with {\"modules\":[{\"cluster_key\":\"...\",\"module_name\":\"...\",\"domain_context\":\"...\",\"stripped_plumbing\":[],\"input_contract\":{},\"output_contract\":{},\"business_rules\":[]}]}.""",
                json.dumps(payload,indent=2)
            )
            by={f"{c['execution_group_id']}:{i}":c for i,c in enumerate(batch,start=start+1)}
            seen=set()
            for m in r.get("modules",[]) or []:
                if not isinstance(m,dict): continue
                key=str(m.get("cluster_key","")); c=by.get(key)
                if not c: continue
                seen.add(key); modules.append({"module_name":str(m.get("module_name",key)),"domain_context":str(m.get("domain_context",c["domain_context"])),"stripped_plumbing":m.get("stripped_plumbing",[]) if isinstance(m.get("stripped_plumbing",[]),list) else [],"input_contract":m.get("input_contract",{}) if isinstance(m.get("input_contract",{}),dict) else {},"output_contract":m.get("output_contract",{}) if isinstance(m.get("output_contract",{}),dict) else {},"business_rules":m.get("business_rules",[]) if isinstance(m.get("business_rules",[]),list) else [],"source_slices":[s.slice_id for s in c["slices"]],"source_files":sorted({s.source_file for s in c["slices"]}),"execution_group_id":c["execution_group_id"]})
            for key,c in by.items():
                if key not in seen:
                    modules.append({"module_name":f"DomainModule_{key}","domain_context":c["domain_context"],"stripped_plumbing":[],"input_contract":{},"output_contract":{},"business_rules":[],"source_slices":[s.slice_id for s in c["slices"]],"source_files":sorted({s.source_file for s in c["slices"]}),"execution_group_id":c["execution_group_id"],"contract_status":"llm_missing_response"})
        return modules


# this method builds module dependencies based on the dependency call graph and the collected slices. It maps slices to their corresponding modules and identifies dependencies between modules based on method calls and type references. It returns a list of module dependency dictionaries, each containing the source module, target module, list of calls, and evidence supporting the dependency.
    def _build_module_dependencies(self, modules, graph, slices):
        slice_to_module={sid:m["module_name"] for m in modules for sid in m.get("source_slices",[])}
        file_to_slices=defaultdict(list); method_to_ids=defaultdict(set); type_to_ids=defaultdict(set)
        for s in slices:
            file_to_slices[s.source_file].append(s)
            if s.name: method_to_ids[s.name].add(s.slice_id)
            if s.kind=="type_declaration" and s.name: type_to_ids[s.name].add(s.slice_id)
        deps={}
        for e in graph.get("edges",[]) or []:
            sf,tf=str(e.get("source","")),str(e.get("target","")); calls=[str(x) for x in e.get("calls",[]) or []]; evidence=set(map(str,e.get("evidence",[]) or []))
            matched=False
            for call in calls:
                tids=method_to_ids.get(call,set())
                for ss in file_to_slices.get(sf,[]):
                    if not re.search(rf"\b{re.escape(call)}\s*\(",ss.text): continue
                    sm=slice_to_module.get(ss.slice_id)
                    if not sm: continue
                    for tid in tids:
                        tm=slice_to_module.get(tid)
                        if tm and tm!=sm:
                            k=(sm,tm); d=deps.setdefault(k,{"calls":set(),"evidence":set()}); d["calls"].add(call); d["evidence"].update(evidence); d["evidence"].add("specific_call_match"); matched=True
            if not matched:
                stem=tf.replace("\\","/").rsplit("/",1)[-1].rsplit(".",1)[0]
                for ss in file_to_slices.get(sf,[]):
                    sm=slice_to_module.get(ss.slice_id)
                    if not sm or not re.search(rf"\b{re.escape(stem)}\b",ss.text): continue
                    for tid in type_to_ids.get(stem,set()):
                        tm=slice_to_module.get(tid)
                        if tm and tm!=sm:
                            k=(sm,tm); d=deps.setdefault(k,{"calls":set(),"evidence":set()}); d["evidence"].update(evidence); d["evidence"].add("specific_type_match"); matched=True
        return [{"source_module":a,"target_module":b,"calls":sorted(d["calls"]),"evidence":sorted(d["evidence"])} for (a,b),d in sorted(deps.items())]


# this method counts the number of dependency edges from the parser that are successfully mapped to module dependencies. It checks if the source and target files of each edge belong to different modules and returns the count of such mapped edges.
    def _count_mapped_edges(self, deps, modules, graph):
        files={m["module_name"]:set(m.get("source_files",[])) for m in modules}; pairs={(x["source_module"],x["target_module"]) for x in deps}; n=0
        for e in graph.get("edges",[]) or []:
            sf,tf=str(e.get("source","")),str(e.get("target",""))
            if any(sf in files.get(a,set()) and tf in files.get(b,set()) for a,b in pairs): n+=1
        return n


__all__=["SplittingAgent","AzureOpenAIJsonClient","SliceRecord"]
