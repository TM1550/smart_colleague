from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass, asdict
import json
import logging
import requests
import numpy as np
import faiss
from sentence_transformers import SentenceTransformer
from pathlib import Path
import pickle
import hashlib
from datetime import datetime

# Настройка логирования
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


# ==================== Data Models ====================


@dataclass
class SearchResult:
    """Результат поиска"""
    description: str
    instruction: str
    user_query: str
    status: str  
    search_time_ms: float = 0.0
    error_message: Optional[str] = None
    similarity_score: Optional[float] = None  # Новое поле для хранения схожести
    
    def to_dict(self) -> Dict[str, Any]:
        """Преобразует в словарь"""
        result = {
            "description": self.description,
            "instruction": self.instruction,
            "user_query": self.user_query,
            "status": self.status,
            "search_time_ms": round(self.search_time_ms, 2),
            "error_message": self.error_message
        }
        if self.similarity_score is not None:
            result["similarity_score"] = round(self.similarity_score, 4)
        return result


# ==================== Vector Store ====================

class VectorStore:
    """Векторное хранилище для инструкций"""
    
    def __init__(self, 
                 model_name: str = 'sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2',
                 use_cosine: bool = True):
        """
        Инициализация векторного хранилища
        
        Args:
            model_name: Название модели для эмбеддингов
            use_cosine: Использовать косинусное расстояние (True) или евклидово (False)
        """
        self.model = SentenceTransformer(model_name)
        self.index = None
        self.instruction_texts = []  # Оригинальные тексты инструкций
        self.instruction_metadata = []  # Метаданные инструкций
        self.use_cosine = use_cosine
        
    def _instruction_to_text(self, instruction: Dict[str, Any]) -> str:
        """Преобразует инструкцию в текст для эмбеддинга"""
        task_name = instruction.get("task_name", "")
        instruction_text = instruction.get("instruction", "")
        # Можно добавить другие поля для лучшего представления
        return f"{task_name}. {instruction_text}"
    
    def build_index(self, instructions: List[Dict[str, Any]]):
        """
        Построение векторного индекса на основе инструкций
        """
        if not instructions:
            logger.warning("Нет инструкций для индексации")
            return
        
        # Сохраняем оригинальные данные
        self.instruction_texts = []
        self.instruction_metadata = []
        
        # Создаем тексты для эмбеддингов
        texts_for_embedding = []
        for i, instr in enumerate(instructions):
            text = self._instruction_to_text(instr)
            texts_for_embedding.append(text)
            self.instruction_texts.append(text)
            self.instruction_metadata.append(instr)
        
        # Создаем эмбеддинги
        logger.info(f"Создание эмбеддингов для {len(texts_for_embedding)} инструкций...")
        embeddings = self.model.encode(texts_for_embedding, 
                                      convert_to_numpy=True, 
                                      show_progress_bar=True)
        
        # Нормализуем векторы для косинусного сходства
        if self.use_cosine:
            faiss.normalize_L2(embeddings)
        
        # Создаем FAISS индекс
        dimension = embeddings.shape[1]
        
        if len(embeddings) > 10000:
            # Для больших наборов используем IVF индекс
            nlist = min(100, len(embeddings) // 39)
            quantizer = faiss.IndexFlatL2(dimension)
            self.index = faiss.IndexIVFFlat(quantizer, dimension, nlist)
            self.index.train(embeddings.astype('float32'))
            self.index.add(embeddings.astype('float32'))
            self.index.nprobe = 10  # Количество ближайших кластеров для поиска
        else:
            # Для небольших наборов используем простой индекс
            if self.use_cosine:
                self.index = faiss.IndexFlatIP(dimension)  # Косинусное сходство
            else:
                self.index = faiss.IndexFlatL2(dimension)  # Евклидово расстояние
        
        self.index.add(embeddings.astype('float32'))
        logger.info(f"✅ Векторный индекс построен. Размерность: {dimension}")
    
    def search_similar(self, query: str, k: int = 10) -> List[Tuple[int, float]]:
        """
        Поиск похожих инструкций по векторному сходству
        
        Args:
            query: Поисковый запрос
            k: Количество возвращаемых результатов
        
        Returns:
            Список кортежей (индекс, сходство)
        """
        if self.index is None or len(self.instruction_texts) == 0:
            logger.warning("Векторный индекс не построен")
            return []
        
        # Создаем эмбеддинг для запроса
        query_embedding = self.model.encode([query], convert_to_numpy=True)
        
        # Нормализуем для косинусного сходства
        if self.use_cosine:
            faiss.normalize_L2(query_embedding)
        
        # Выполняем поиск
        distances, indices = self.index.search(query_embedding.astype('float32'), min(k, len(self.instruction_texts)))
        
        results = []
        for i, (distance, idx) in enumerate(zip(distances[0], indices[0])):
            if idx >= 0 and idx < len(self.instruction_texts):
                # Преобразуем расстояние в схожесть
                if self.use_cosine:
                    similarity = distance  # Для косинусного сходства это уже схожесть
                else:
                    similarity = 1 / (1 + distance)  # Преобразуем евклидово расстояние в схожесть
                
                if similarity > 0:  # Фильтруем слишком низкую схожесть
                    results.append((idx, similarity))
        
        # Сортируем по убыванию схожести
        results.sort(key=lambda x: x[1], reverse=True)
        return results
    
    def get_instruction_by_index(self, idx: int) -> Optional[Dict[str, Any]]:
        """Получение инструкции по индексу"""
        if 0 <= idx < len(self.instruction_metadata):
            return self.instruction_metadata[idx]
        return None
    
    def save_index(self, path: str):
        """Сохранение индекса на диск"""
        if self.index:
            # Сохраняем данные
            data = {
                'instruction_texts': self.instruction_texts,
                'instruction_metadata': self.instruction_metadata,
                'use_cosine': self.use_cosine
            }
            
            with open(f"{path}_data.pkl", 'wb') as f:
                pickle.dump(data, f)
            
            # Сохраняем FAISS индекс
            faiss.write_index(self.index, f"{path}_index.faiss")
            
            # Сохраняем модель (только информацию о ней)
            model_info = {
                'model_name': self.model[0].auto_model.config._name_or_path,
                'use_cosine': self.use_cosine
            }
            with open(f"{path}_model.pkl", 'wb') as f:
                pickle.dump(model_info, f)
            
            logger.info(f"✅ Векторный индекс сохранен в {path}")
    
    def load_index(self, path: str):
        """Загрузка индекса с диска"""
        try:
            # Загружаем данные
            with open(f"{path}_data.pkl", 'rb') as f:
                data = pickle.load(f)
                self.instruction_texts = data['instruction_texts']
                self.instruction_metadata = data['instruction_metadata']
                self.use_cosine = data.get('use_cosine', True)
            
            # Загружаем FAISS индекс
            self.index = faiss.read_index(f"{path}_index.faiss")
            
            # Загружаем информацию о модели
            with open(f"{path}_model.pkl", 'rb') as f:
                model_info = pickle.load(f)
                # Переинициализируем модель
                self.model = SentenceTransformer(model_info['model_name'])
            
            logger.info(f"✅ Векторный индекс загружен из {path}")
        except Exception as e:
            logger.error(f"❌ Ошибка загрузки индекса: {e}")


# ==================== API Client ====================

class LLMClient:
    """Клиент для взаимодействия с LLM API"""
    
    def __init__(
        self,
        api_key: str,
        model: str = "tngtech/deepseek-r1t2-chimera:free",
        base_url: str = "https://openrouter.ai/api/v1/chat/completions",
        timeout: int = 120
    ):
        self.api_key: str = api_key
        self.base_url: str = base_url
        self.model: str = model
        self.timeout: int = timeout
            
    def call_api(self, messages: List[Dict[str, str]], temperature: float = 0.7) -> str:
        """Низкоуровневый вызов API"""
        
        payload: Dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
        }
        
        headers: Dict[str, str] = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        
        try:
            response: requests.Response = requests.post(
                self.base_url,
                headers=headers,
                json=payload,
                timeout=self.timeout,
            )
            response.raise_for_status()
            
            data = response.json()
            return data["choices"][0]["message"]["content"].strip()
        
        except requests.exceptions.Timeout:
            logger.error("❌ API request timed out")
            raise RuntimeError("API request timed out")
        
        except requests.exceptions.HTTPError as e:
            logger.error(f"❌ HTTP Error: {e.response.status_code}")
            raise RuntimeError(f"HTTP Error: {e.response.status_code}")
        
        except Exception as e:
            logger.error(f"❌ API error: {e}")
            raise RuntimeError(f"API error: {str(e)}")


# ==================== Instruction Search Engine ====================

class InstructionSearchEngine:
    """Поисковый движок для инструкций с векторным поиском"""
    
    def __init__(self, 
                 llm_client: LLMClient,
                 vector_model: str = 'sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2',
                 use_vector_search: bool = True,
                 similarity_threshold: float = 0.3):
        self.llm_client: LLMClient = llm_client
        self.vector_store = VectorStore(model_name=vector_model) if use_vector_search else None
        self.use_vector_search = use_vector_search
        self.similarity_threshold = similarity_threshold
    
    def build_vector_index(self, instructions: List[Dict[str, Any]]):
        """Построение векторного индекса"""
        if self.vector_store:
            self.vector_store.build_index(instructions)
    
    def vector_search_candidates(self, user_query: str, top_k: int = 20) -> List[Tuple[Dict[str, Any], float]]:
        """
        Поиск кандидатов с помощью векторного поиска
        
        Returns:
            Список кортежей (инструкция, схожесть)
        """
        if not self.vector_store or not self.use_vector_search:
            return []
        
        candidates = []
        vector_results = self.vector_store.search_similar(user_query, k=top_k)
        
        for idx, similarity in vector_results:
            if similarity >= self.similarity_threshold:
                instruction = self.vector_store.get_instruction_by_index(idx)
                if instruction:
                    candidates.append((instruction, similarity))
        
        logger.info(f"🔍 Векторный поиск нашел {len(candidates)} кандидатов (порог: {self.similarity_threshold})")
        return candidates
    
    def _extract_relevance_score(self, response_text: str) -> float:
        """Извлекает оценку релевантности из ответа LLM"""
        try:
            # Пытается найти JSON в ответе
            import re
            json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
            if json_match:
                data = json.loads(json_match.group())
                score = data.get("relevance_score", 0.0)
                return float(score) / 100.0 if score > 1 else float(score)
        except:
            pass
        
        # Fallback: ищет числа в тексте
        import re
        scores = re.findall(r'\b(0\.\d+|[0-9]+)\b', response_text)
        if scores:
            try:
                score = float(scores[0])
                return score / 100.0 if score > 1 else score
            except:
                pass
        
        return 0.5  # Дефолтное значение
    
    def evaluate_instruction_relevance(
        self,
        user_query: str,
        instruction: str,
    ) -> tuple[float, str, str, str]:
        """
        Оценивает релевантность инструкции к запросу пользователя
        
        Returns:
            tuple: (score, reasoning, instruction, description)
        """
        prompt = f"""Ты — эксперт по анализу инструкции. Оцени, насколько предложенная инструкция соответствует запросу пользователя.

Запрос пользователя: "{user_query}"

Инструкция: {instruction}

Проанализируй:
1. Совпадает ли задача инструкции с запросом пользователя?
2. Есть ли семантическое сходство между инструкцией и запросом?
3. Поможет ли эта инструкция пользователю решить его задачу?

Ответь JSON-объектом:
{{
  "relevance_score": <число от 0 до 1>,
  "instruction": <полностью написанная соответствующая инструкция>,
  "reasoning": "<краткое объяснение на русском, 1-2 предложения>",
  "description": "<пошаговое описание инструкции, понятное и не слишком длинное>"
}}

Ответ (только JSON, без других текстов):"""
        
        try:
            logger.info(f"Оценка релевантности запроса: '{user_query[:50]}...'")
            
            response = self.llm_client.call_api(
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3
            )
            
            # Парсим JSON из ответа
            import re
            json_match = re.search(r'\{.*\}', response, re.DOTALL)
            
            if json_match:
                try:
                    data = json.loads(json_match.group())
                    score = float(data.get("relevance_score", 0.5))
                    found_instruction = str(data.get("instruction", ""))
                    description = str(data.get("description", ""))
                    reasoning = str(data.get("reasoning", "Нет объяснения"))
                    
                    # Нормализуем score
                    score = max(0.0, min(1.0, score))
                    
                    logger.info(f"  ✓ Score: {score:.2f}, Reasoning: {reasoning[:50]}...")
                    return score, reasoning, found_instruction, description
                
                except json.JSONDecodeError:
                    logger.warning(f"  ⚠️ Не удалось распарсить JSON из ответа")
                    return 0.5, "Ошибка парсинга ответа API", "", ""
            else:
                logger.warning(f"  ⚠️ JSON не найден в ответе")
                return 0.5, "API вернул неправильный формат", "", ""
        
        except Exception as e:
            logger.error(f"  ❌ Ошибка оценки релевантности: {e}")
            return 0.0, f"Ошибка: {str(e)}", "", ""

    def search_hybrid(
        self,
        user_query: str,
        instructions: List[Dict[str, Any]],
        vector_top_k: int = 10,
        llm_top_k: int = 3,
        min_relevance: float = 0.2
    ) -> SearchResult:
        """
        Гибридный поиск: сначала векторный, затем уточнение через LLM
        
        Args:
            user_query: Запрос пользователя
            instructions: Полный список инструкций (если нужно перестроить индекс)
            vector_top_k: Сколько кандидатов искать через векторный поиск
            llm_top_k: Сколько кандидатов оценивать через LLM
            min_relevance: Минимальная релевантность
        
        Returns:
            SearchResult с найденными инструкциями
        """
        import time
        start_time = time.time()
        
        logger.info(f"🔍 Начинаю гибридный поиск для запроса: '{user_query}'")
        
        # Шаг 1: Векторный поиск кандидатов
        candidates = []
        if self.use_vector_search:
            candidates = self.vector_search_candidates(user_query, top_k=vector_top_k)
        else:
            # Если векторный поиск отключен, используем все инструкции
            candidates = [(instr, 0.5) for instr in instructions]
        
        if not candidates:
            logger.warning("❌ Не найдено кандидатов для оценки")
            search_time = (time.time() - start_time) * 1000
            return SearchResult(
                description="",
                instruction="",
                user_query=user_query,
                status="no_matches",
                search_time_ms=search_time,
                error_message="Не найдено подходящих инструкций"
            )
        
        logger.info(f"📊 Найдено {len(candidates)} кандидатов через векторный поиск")
        
        # Шаг 2: Оценка топ-N кандидатов через LLM
        best_score = 0.0
        best_instruction = ""
        best_description = ""
        best_reasoning = ""
        best_similarity = 0.0
        
        # Ограничиваем количество кандидатов для оценки LLM
        candidates_to_evaluate = candidates[:min(llm_top_k, len(candidates))]
        
        for candidate, similarity in candidates_to_evaluate:
            instruction_text = self._instruction_to_str(candidate)
            score, reasoning, found_instr, description = self.evaluate_instruction_relevance(
                user_query, instruction_text
            )
            
            # Комбинированная оценка: учитываем и векторную схожесть, и оценку LLM
            combined_score = (similarity * 0.4) + (score * 0.6)
            
            if combined_score > best_score and score >= min_relevance:
                best_score = combined_score
                best_similarity = similarity
                best_instruction = found_instr
                best_description = description
                best_reasoning = reasoning
        
        search_time = (time.time() - start_time) * 1000
        
        if best_score < min_relevance:
            logger.warning("❌ Не найдено достаточно релевантных инструкций")
            return SearchResult(
                description="",
                instruction="",
                user_query=user_query,
                status="no_matches",
                search_time_ms=search_time,
                error_message=f"Лучшая оценка релевантности ({best_score:.2f}) ниже порога ({min_relevance})"
            )
        
        logger.info(f"✅ Поиск завершен. Лучшая оценка: {best_score:.2f} (vector: {best_similarity:.2f})")
        
        return SearchResult(
            description=best_description,
            instruction=best_instruction,
            user_query=user_query,
            status="success",
            search_time_ms=search_time,
            similarity_score=best_score
        )
    
    def _instruction_to_str(self, instruction: Dict[str, Any]) -> str:
        """Преобразует инструкцию в строку для оценки"""
        task_name = instruction.get("task_name", "")
        full_path = instruction.get("full_path", "")
        instruction_text = instruction.get("instruction", "")
        
        return f"Задача: {task_name}\nПуть: {full_path}\nИнструкция:\n{instruction_text}"
    
    def search(
        self,
        user_query: str,
        instructions: List[Dict[str, Any]],
    ) -> SearchResult:
        """
        Основной метод поиска (обратная совместимость)
        """
        return self.search_hybrid(user_query, instructions)


# ==================== Question Processor ====================

class QuestionProcessor:
    """Обработчик вопросов и генерация рекомендаций"""
    
    def __init__(self, llm_client: LLMClient, search_engine: InstructionSearchEngine):
        self.llm_client: LLMClient = llm_client
        self.search_engine: InstructionSearchEngine = search_engine
    
    def generate_recommendation(
        self,
        user_query: str,
        search_result: SearchResult
    ) -> str:
        """
        Генерирует рекомендацию на основе результатов поиска
        
        Args:
            user_query: Исходный запрос пользователя
            search_result: Результаты поиска
        
        Returns:
            Текст рекомендации
        """
        
        if search_result.status == "no_matches":
            return f"К сожалению, я не нашел подходящих инструкций для вашего запроса: '{user_query}'. Попробуйте переформулировать вопрос или обратитесь к главному меню."
        
        top_match = search_result.instruction
        
        if not top_match:
            return "Ошибка: не найдено совпадений"
        
        prompt = f"""Ты — помощник пользователя. На основе найденной инструкции дай краткий совет пользователю.

Запрос пользователя: "{user_query}"

Найденная инструкция:
- Инструкция: {top_match}
- Описание: {search_result.description}

Напиши ответ на русском языке:
1. Подтверди, что ты понял запрос пользователя
2. Предложи найденную инструкцию
3. Если нужно — дай краткие пояснения
4. Будь дружелюбным и полезным

Ответ (2-3 предложения, дружелюбный тон):"""
        
        try:
            recommendation = self.llm_client.call_api(
                messages=[{"role": "user", "content": prompt}],
                temperature=0.7
            )
            return recommendation
        
        except Exception as e:
            logger.error(f"Ошибка генерации рекомендации: {e}")
            # Fallback ответ
            return f"Попробуйте выполнить следующую инструкцию: {top_match[:200]}..."


# ==================== Main Interface ====================

class InstructionAssistant:
    """Главный интерфейс ассистента по инструкциям"""
    
    def __init__(self, 
                 api_key: str,
                 use_vector_search: bool = True,
                 vector_model: str = 'sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2'):
        self.llm_client = LLMClient(api_key=api_key)
        self.search_engine = InstructionSearchEngine(
            llm_client=self.llm_client,
            use_vector_search=use_vector_search,
            vector_model=vector_model
        )
        self.question_processor = QuestionProcessor(
            llm_client=self.llm_client,
            search_engine=self.search_engine
        )
        self.current_instructions: List[Dict[str, Any]] = []
        self.use_vector_search = use_vector_search
    
    def load_instructions(self, instructions: List[Dict[str, Any]]) -> None:
        """
        Загружает инструкции и строит векторный индекс
        
        Args:
            instructions: Список инструкций
        """
        self.current_instructions = instructions
        
        if self.use_vector_search:
            logger.info(f"🔨 Построение векторного индекса для {len(instructions)} инструкций...")
            self.search_engine.build_vector_index(instructions)
        
        logger.info(f"✅ Загружено {len(instructions)} инструкций")
    
    def save_vector_index(self, path: str = "./vector_index"):
        """Сохраняет векторный индекс на диск"""
        if self.use_vector_search and self.search_engine.vector_store:
            self.search_engine.vector_store.save_index(path)
    
    def load_vector_index(self, path: str = "./vector_index"):
        """Загружает векторный индекс с диска"""
        if self.use_vector_search and self.search_engine.vector_store:
            self.search_engine.vector_store.load_index(path)
    
    def answer_question(
        self,
        user_query: str,
        vector_top_k: int = 15,
        llm_top_k: int = 3,
        min_relevance: float = 0.3,
        include_recommendation: bool = True
    ) -> Dict[str, Any]:
        """
        Отвечает на вопрос пользователя с использованием векторного поиска
        
        Args:
            user_query: Вопрос пользователя
            vector_top_k: Количество кандидатов для векторного поиска
            llm_top_k: Количество кандидатов для оценки LLM
            min_relevance: Минимальная релевантность
            include_recommendation: Генерировать ли рекомендацию
        
        Returns:
            Словарь с результатами
        """
        
        if not self.current_instructions:
            return {
                "status": "error",
                "error_message": "Инструкции не загружены. Используйте load_instructions()."
            }
        
        logger.info(f"\n{'='*60}")
        logger.info(f"💬 Вопрос пользователя: '{user_query}'")
        logger.info(f"{'='*60}")
        
        # Поиск релевантных инструкций
        search_result = self.search_engine.search_hybrid(
            user_query=user_query,
            instructions=self.current_instructions,
            vector_top_k=vector_top_k,
            llm_top_k=llm_top_k,
            min_relevance=min_relevance
        )
        
        result_dict = search_result.to_dict()
        
        # Добавляем рекомендацию если нужно
        if include_recommendation and search_result.status == "success":
            recommendation = self.question_processor.generate_recommendation(
                user_query=user_query,
                search_result=search_result
            )
            result_dict["recommendation"] = recommendation
        
        logger.info(f"✅ Обработка вопроса завершена за {search_result.search_time_ms:.0f}мс")
        
        return result_dict