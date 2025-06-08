"""Aplicación GUI para practicar ejercicios de álgebra con retroalimentación
automática de un LLM.

Requisitos finales
------------------
* **Barra de título** de la ventana: siempre «Tutor de Algebra».
* **Encabezado interno**: se muestra **solo** si el JSON trae explícitamente un
  campo `titulo` (no importa cuál). Si el archivo no incluye `titulo`, el
  encabezado se omite por completo.
"""

import json
import random
import re
import tkinter as tk
from tkinter import scrolledtext
from pathlib import Path
import requests
from dataclasses import dataclass
from typing import List, Dict, Tuple

# ───────────── Config & Data Models ──────────────
@dataclass
class LLMConfig:
    url: str
    model: str
    temperature: float = 0.5
    max_tokens: int = 500
    timeout: int = 90

    @classmethod
    def from_file(cls, path: Path = Path("llm_config.json")) -> "LLMConfig":
        data = json.loads(path.read_text(encoding="utf-8"))
        data.setdefault("timeout", cls.timeout)
        return cls(**data)

@dataclass
class PromptTemplates:
    system: str
    all_correct: str
    some_wrong: str
    all_wrong: str

    @classmethod
    def from_file(cls, path: Path = Path("prompts.json")) -> "PromptTemplates":
        data: Dict = json.loads(path.read_text(encoding="utf-8"))
        return cls(
            system=data["system_prompt"],
            all_correct=data["user_prompts"]["all_correct"],
            some_wrong=data["user_prompts"]["some_wrong"],
            all_wrong=data["user_prompts"]["all_wrong"],
        )

@dataclass
class Question:
    statement: str
    answer: str

# ───────────── Helpers ──────────────

def load_questions(path: Path = Path("preguntas.json")) -> Tuple[str, List[Question]]:
    """Devuelve (titulo, lista_de_preguntas).

    * Si el JSON trae la clave "titulo", se devuelve ese texto.
    * Si no existe, se devuelve la cadena vacía "".
    """
    data = json.loads(path.read_text(encoding="utf-8"))
    titulo = data.get("titulo", "")  # cadena vacía por defecto
    preguntas = [Question(q["pregunta"], q["respuesta"]) for q in data["preguntas"]]
    return titulo, preguntas

# ───────────── Main Application ──────────────
class MathTutorApp:
    def __init__(self, questions: List[Question], llm_cfg: LLMConfig, prompts: PromptTemplates, title: str, n: int = 2):
        self.questions = random.sample(questions, n) if n <= len(questions) else questions
        self.cfg = llm_cfg
        self.prompts = prompts
        self.title_text = title.strip()

        self.entries: List[tk.Entry] = []
        self.labels: List[tk.Label] = []

        self.root = tk.Tk()
        self.root.title("Tutor de Algebra")
        self._build_ui()

    # ---------- GUI BUILDERS ----------
    def _build_ui(self):
        # Mostrar encabezado solo si se proporcionó un título en el JSON
        if self.title_text:
            tk.Label(self.root, text=self.title_text, font=("Arial", 14, "bold")).pack(pady=10)

        for idx, q in enumerate(self.questions, start=1):
            frame = tk.Frame(self.root)
            frame.pack(fill="x", padx=10, pady=5)
            tk.Label(frame, text=f"{idx}. {q.statement}", font=("Arial", 12)).pack(side="left")
            ent = tk.Entry(frame, width=25, font=("Arial", 12))
            ent.pack(side="left", padx=5)
            tk.Button(frame, text="Enviar", font=("Arial", 12), bg="#4CAF50", fg="white", command=lambda i=idx-1: self._check_answer(i)).pack(side="left", padx=5)
            lbl = tk.Label(frame, font=("Arial", 12))
            lbl.pack(side="left", padx=5)
            self.entries.append(ent)
            self.labels.append(lbl)

        self.tutor_btn = tk.Button(self.root, text="Retroalimentación del tutor", command=self._tutor_feedback, state="disabled", font=("Arial", 12), bg="#3F51B5", fg="white")
        self.tutor_btn.pack(pady=10)
        self.feedback = scrolledtext.ScrolledText(self.root, width=85, height=12, font=("Arial", 11), wrap=tk.WORD, state="disabled")
        self.feedback.pack(padx=10, pady=5)

    # ---------- CORE LOGIC ----------
    @staticmethod
    def _norm(txt: str) -> str:
        expr = txt.lower().replace(" ", "").strip().replace(")(", ")*(")
        if "*" not in expr:
            return expr.strip("()")
        factors = sorted(f.strip("()") for f in expr.split("*") if f)
        return "*".join(factors)

    @staticmethod
    def _strip_hidden_thoughts(text: str) -> str:
        import re

        cleaned = re.sub(r"<think>.*?</think>", "", text, flags=re.I | re.S)
        cleaned = re.sub(r"(?m)^\s*(thought|razonamiento|assistant reasoning).*", "", cleaned, flags=re.I)
        cleaned = re.sub(r"(?m)^#+\s*", "", cleaned)
        # ① Elimina delimitadores LaTeX  (\…\)  y  [ … ]
        latex_inline = re.compile(r"\\\((.*?)\\\)", flags=re.S)          # \( … \)
        latex_block  = re.compile(r"\\\[([\s\S]*?)\\\]", flags=re.S)     # \[ … ]
        cleaned = latex_inline.sub(r"\1", cleaned)
        cleaned = latex_block.sub(r"\1", cleaned)

        # --- elimina LaTeX ---
        cleaned = re.sub(r"\\\((.*?)\\\)", r"\1", cleaned, flags=re.S)        # \( … \)
        cleaned = re.sub(r"\\\[([\s\S]*?)\\\]", r"\1", cleaned, flags=re.S)   # \[ … ]
        cleaned = re.sub(r"\$\$([\s\S]*?)\$\$", r"\1", cleaned, flags=re.S)   # $$ … $$

        # --- quita paréntesis triviales ---
        cleaned = re.sub(r"\((\w)\)", r"\1", cleaned)

        # --- convierte exponentes a superíndice Unicode ---
        super_map = str.maketrans("0123456789", "⁰¹²³⁴⁵⁶⁷⁸⁹")
        cleaned = re.sub(
            r"\^([0-9]+)",
            lambda m: ''.join(ch.translate(super_map) for ch in m.group(1)),
            cleaned
        )

        return cleaned.replace("#", "").strip()

    def _check_answer(self, idx: int):
        user = self.entries[idx].get()
        correct = self.questions[idx].answer
        ok = self._norm(user) == self._norm(correct)
        self.labels[idx].config(text="Correcto" if ok else "Incorrecto", fg="green" if ok else "red")
        if ok:
            self.entries[idx].config(state="disabled")
        self.tutor_btn.config(state="normal")

    def _gather_wrong_answers(self):
        return [(i, ent.get()) for i, ent in enumerate(self.entries) if self._norm(ent.get()) != self._norm(self.questions[i].answer)]

    def _tutor_feedback(self):
        wrong_answers = self._gather_wrong_answers()
        if not wrong_answers:
            prompt = self.prompts.all_correct
        elif len(wrong_answers) == len(self.questions):
            detalles = "\n\n".join(f"Pregunta: {self.questions[i].statement}\nRespuesta del estudiante: {ans}\nRespuesta correcta: {self.questions[i].answer}" for i, ans in wrong_answers)
            prompt = self.prompts.all_wrong.format(n_errors=len(wrong_answers), details=detalles)
        else:
            detalles = "\n\n".join(f"Pregunta: {self.questions[i].statement}\nRespuesta del estudiante: {ans}\nRespuesta correcta: {self.questions[i].answer}" for i, ans in wrong_answers)
            prompt = self.prompts.some_wrong.format(n_errors=len(wrong_answers), details=detalles)
        reply = self._ask_llm(prompt)
        self._show_feedback(reply)

    def _ask_llm(self, user_prompt: str) -> str:
        if "/no_think" not in user_prompt:
            user_prompt = user_prompt.rstrip() + " /no_think"
        payload = {"model": self.cfg.model, "messages": [{"role": "system", "content": self.prompts.system}, {"role": "user", "content": user_prompt}], "temperature": self.cfg.temperature, "max_tokens": self.cfg.max_tokens}
        try:
            r = requests.post(self.cfg.url, json=payload, timeout=self.cfg.timeout)
            r.raise_for_status()
            raw = r.json()["choices"][0]["message"]["content"].strip()
            return self._strip_hidden_thoughts(raw)
        except Exception as exc:
            return f"Error al consultar LLM: {exc}"

    def _show_feedback(self, text: str):
        self.feedback.config(state="normal")
        self.feedback.delete("1.0", tk.END)
        self.feedback.insert(tk.END, text)
        self.feedback.config(state="disabled")

    def run(self):
        self.root.mainloop()

# ───────────── Bootstrap ──────────────

def main():
    try:
        llm_cfg = LLMConfig.from_file()
        prompts = PromptTemplates.from_file()
        title, questions = load_questions()
        MathTutorApp(questions, llm_cfg, prompts, title=title, n=2).run()
    except Exception as exc:
        print(f"Error al iniciar la aplicación: {exc}")

if __name__ == "__main__":
    main()

