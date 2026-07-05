# User Flow: Gemma-Powered Language Learning Memory System

## Product Concept

This app helps users learn languages from the materials they already read, upload, search, and study. Instead of being only a flashcard generator, the app acts as a personalized learning memory system.

The core promise:

> Users can upload documents, generate vocabulary flashcards, ask questions, take quizzes, practice conversations, and track everything they have learned over time.

The most important product principle is:

> Always keep a record of everything the user has learned, searched, uploaded, practiced, and struggled with.

## Target Users

- Students learning English, Spanish, Vietnamese, French, or Chinese.
- Language learners who want vocabulary from real documents instead of random word lists.
- Users preparing for school, travel, work, exams, or daily conversation.
- Learners who want progress tracking and personalized review.

## Supported Languages

The first version focuses on five main languages:

- English
- Spanish
- Vietnamese
- French
- Chinese

Each user chooses a target language and may also choose a native/explanation language for meanings, hints, and examples.

## Main User Journey

### 1. Onboarding

The user opens the app and starts with a short setup flow.

User actions:

1. Choose target language.
2. Choose current level if known.
3. Choose learning goal.
4. Optionally take a placement test.

Possible goals:

- Learn daily conversation vocabulary.
- Study vocabulary from documents.
- Prepare for an exam.
- Improve reading comprehension.
- Practice speaking and writing.
- Review words already learned.

System actions:

- Create a learner profile.
- Store selected language, level, goal, and preferred learning style.
- Recommend a starting roadmap.

## Placement Test And Roadmap

### Placement Test

If the user does not know their level, they can take an entry test.

Test structure:

- Vocabulary recognition.
- Fill-in-the-blank questions.
- Short reading comprehension.
- Basic grammar questions.
- Optional writing prompt.

Gemma analyzes:

- Vocabulary range.
- Grammar accuracy.
- Reading comprehension.
- Common mistakes.
- Confidence level.

Output:

- Estimated level, such as A1, A2, B1, B2, C1.
- Weak areas.
- Suggested roadmap.
- Recommended first topics.

### Learning Roadmap

The app generates 3 to 4 roadmap levels from lower to higher difficulty.

Example:

1. Foundation vocabulary.
2. Topic-based vocabulary.
3. Real document reading.
4. Conversation and active usage.

Each roadmap includes:

- Topics to study.
- Suggested vocabulary count.
- Quiz schedule.
- Review frequency.
- Conversation practice prompts.

## Home Dashboard

After onboarding, the user lands on the dashboard.

Dashboard shows:

- Current target language.
- Current level.
- Words learned.
- Words searched.
- Words mastered.
- Weak words.
- Quiz accuracy.
- Streak progress.
- Improvement percentage.
- Recent uploaded files.
- Recent decks.
- Recommended next activity.

Main dashboard actions:

- Upload document.
- Generate flashcards.
- Search dictionary.
- Start quiz.
- Practice conversation.
- Ask Gemma about uploaded files.
- Review weak words.
- Continue roadmap.

## Content Upload Flow

The user can upload or paste learning material.

Supported inputs:

- PDF files.
- Passages.
- Papers.
- Notes.
- Text documents.
- Excel files.
- Vocabulary lists.

### Document Upload

User actions:

1. Click upload.
2. Select file or paste text.
3. Choose target language.
4. Choose output type.
5. Choose maximum number of words or cards.

Output options:

- Generate flashcards.
- Extract key vocabulary.
- Summarize document.
- Ask questions about document.
- Create quiz.
- Save document to learning history.

System actions:

- Extract text from the file.
- Detect topics.
- Identify useful vocabulary.
- Group words by topic.
- Estimate difficulty.
- Save upload metadata and extracted vocabulary.

Stored data:

- File name.
- Upload date.
- Extracted topics.
- Extracted words.
- Generated flashcards.
- User-selected saved words.
- Questions asked about the document.

## Excel Upload Flow

Excel upload supports user-created word lists.

Possible columns:

- Word.
- Meaning.
- Example.
- Topic.
- Difficulty.
- Native language translation.
- Notes.

User actions:

1. Upload Excel file.
2. Preview detected columns.
3. Confirm or map columns manually.
4. Generate flashcards.
5. Save deck.

System actions:

- Parse rows.
- Clean duplicate words.
- Detect missing meanings or examples.
- Use Gemma to fill missing fields.
- Create a deck from the uploaded vocabulary.

## Flashcard Generation Flow

Flashcards can be generated from multiple sources.

Sources:

- User-chosen topic.
- Uploaded document.
- Uploaded Excel file.
- Saved words.
- Weak words.
- Previous vocabulary history.
- Roadmap topic.
- Dictionary searches.

User actions:

1. Choose language.
2. Choose source.
3. Choose topic.
4. Set max number of words.
5. Generate deck.
6. Review cards.
7. Save, edit, or remove cards.

Gemma generates:

- Front term.
- Meaning.
- Example sentence.
- Topic tag.
- Difficulty level.
- Pronunciation hint if useful.
- Memory tip.
- Related words.

Important behavior:

- Avoid repeating already mastered words unless the user wants review.
- Prefer words from user-uploaded materials.
- Include previously learned related words when useful.
- Generate different words each time if the user asks for new vocabulary.

## Topic-Based Learning Flow

The user can generate flashcards by topic.

Example topics:

- Sports.
- Soccer.
- Food.
- School.
- Travel.
- Business.
- Health.
- Daily routine.

Flow:

1. User chooses target language.
2. User enters or selects a topic.
3. User chooses number of new words, such as 20.
4. Gemma generates vocabulary.
5. App checks history to avoid unnecessary repetition.
6. User studies the deck.
7. Words are saved to history.

Topic continuity:

If the user first studies "sports" and later studies "soccer," the app uses previous sports vocabulary to explain soccer vocabulary, create examples, and build conversation practice.

## Dictionary Search Flow

The user can search for any word from a file or manually enter a word.

User actions:

1. Highlight a word in an uploaded file or type a word.
2. Click dictionary search.
3. View meaning, examples, and usage.
4. Add the word to a flashcard deck.

Gemma returns:

- Meaning.
- Simple explanation.
- Example sentence.
- Translation.
- Topic.
- Difficulty.
- Similar words.
- Common mistakes.

Stored data:

- Searched word.
- Search date.
- Source document if applicable.
- Whether the user added it to flashcards.
- Whether the user later mastered it.

## Ask Gemma Flow

The user can ask Gemma questions while studying.

Question types:

- What does this word mean?
- Explain this sentence.
- Summarize this paragraph.
- What are the key vocabulary words here?
- Make flashcards from this section.
- Give me easier examples.
- Explain this grammar point.

System behavior:

- If the question is about an uploaded file, answer using the file context.
- If the question is about vocabulary, connect it to the user's learning history.
- If the question includes a saved word, update that word's activity history.

## Semantic Study Search Flow

Semantic study search allows users to ask questions based on uploaded files.

User actions:

1. Upload one or more files.
2. Ask a question.
3. Receive an answer grounded in the uploaded material.
4. Generate cards or quiz questions from the answer.

Example:

User asks:

> What are the most important vocabulary words in chapter 2?

Gemma responds with:

- Important words.
- Meanings.
- Examples.
- Topic groups.
- Suggested flashcards.

Stored data:

- Question.
- Answer.
- Related document.
- Generated words.
- Follow-up actions.

## Quiz Flow

Quizzes reinforce memory after flashcard study.

Quiz types:

- Multiple choice.
- Fill in the blank.
- Spelling.
- Matching.
- Meaning recall.
- Example completion.

User actions:

1. Choose quiz source.
2. Choose quiz type.
3. Start quiz.
4. Answer questions.
5. Review results.
6. Save weak words for review.

Quiz sources:

- Current deck.
- Weak words.
- Words learned today.
- Words from a document.
- Words from a topic.
- Words from previous weeks.

System actions:

- Generate quiz questions.
- Score answers.
- Explain mistakes.
- Mark words as strong, weak, or mastered.
- Update progress dashboard.

Tracked metrics:

- Accuracy.
- Time spent.
- Attempts per word.
- Mistake type.
- Quiz type performance.
- Improvement over time.

## Conversation Practice Flow

Conversation practice forces the user to actively use new vocabulary.

User actions:

1. Choose conversation topic.
2. Choose difficulty level.
3. Choose words to practice.
4. Chat with Gemma.
5. Receive corrections and suggestions.

Gemma behavior:

- Use words the user just learned.
- Reuse related older vocabulary.
- Ask questions that require target words.
- Correct grammar and word choice.
- Give hints without immediately revealing answers.
- Summarize performance after the conversation.

Example:

If the user studied sports vocabulary and later studies soccer vocabulary, Gemma creates a soccer conversation using both new soccer words and older sports words.

Stored data:

- Conversation topic.
- Words used correctly.
- Words missed.
- Corrections.
- Suggested review words.
- Fluency notes.

## Learning Memory System

This is the core of the product.

The app records everything meaningful the user does.

Tracked items:

- Uploaded files.
- Extracted vocabulary.
- Generated flashcards.
- Manually added words.
- Dictionary searches.
- Quiz results.
- Conversation practice.
- Weak words.
- Mastered words.
- Roadmap progress.
- Topics studied.
- Questions asked.
- Gemma answers.

Each vocabulary item should store:

- Word or phrase.
- Language.
- Meaning.
- Example.
- Source.
- Topic.
- Difficulty.
- First seen date.
- Last reviewed date.
- Review count.
- Quiz accuracy.
- Mastery status.
- User notes.

Mastery statuses:

- New.
- Learning.
- Weak.
- Reviewing.
- Mastered.

## Progress Dashboard

The dashboard turns learning history into visible progress.

Graphs and stats:

- Words learned over time.
- Quiz accuracy over time.
- Streak progress.
- Topic coverage.
- Weak vs mastered words.
- Time spent studying.
- Improvement percentage.
- New words by source.
- Most difficult topics.

Dashboard cards:

- Total words learned.
- Words mastered.
- Weak words to review.
- Current streak.
- Best quiz score.
- Recent improvement.
- Recommended next topic.

AI-generated report:

- Weekly summary.
- Strong areas.
- Weak areas.
- Suggested next lessons.
- Recommended review deck.

## Review And Spaced Practice Flow

The app should help users review before they forget.

System behavior:

- Prioritize weak words.
- Bring back words not reviewed recently.
- Mix old words with new related words.
- Increase difficulty as accuracy improves.
- Reduce repetition for mastered words.

Daily review flow:

1. User opens dashboard.
2. App recommends review session.
3. User reviews flashcards.
4. User takes short quiz.
5. App updates mastery status.
6. Gemma recommends next activity.

## Public Source And Social Media Learning

This is an advanced future feature.

Goal:

Let users learn from public content they care about, such as articles, posts, or social media text.

Possible flow:

1. User adds a public article, post, or text source.
2. App extracts useful vocabulary.
3. Gemma explains vocabulary in context.
4. User saves selected words.
5. App adds them to future review.

Important limits:

- The app should clearly show source and date.
- The app should avoid claiming that generated content is always up to date.
- Public-source learning should be optional.
- User privacy and content permissions must be respected.

## Main Navigation

Suggested app sections:

- Dashboard.
- Upload.
- Flashcards.
- Quiz.
- Dictionary.
- Ask Gemma.
- Conversation.
- Roadmap.
- History.
- Settings.

## Data Model Overview

Main entities:

- UserProfile.
- UploadedDocument.
- VocabularyItem.
- FlashcardDeck.
- Flashcard.
- QuizSession.
- QuizAnswer.
- ConversationSession.
- DictionarySearch.
- Roadmap.
- ProgressSnapshot.

Important relationships:

- A user has many uploaded documents.
- A document has many extracted vocabulary items.
- A vocabulary item can appear in many flashcards.
- A deck contains many flashcards.
- A quiz session tests many vocabulary items.
- Conversation sessions use selected vocabulary items.
- Progress snapshots summarize learning over time.

## Minimum Strong Version

The strongest first complete version should include:

1. Language selection.
2. Topic-based flashcard generation.
3. Upload passage or PDF.
4. Generate flashcards from uploaded text.
5. Save generated words to history.
6. Dictionary search.
7. Add searched words to flashcards.
8. Multiple-choice quiz.
9. Fill-in-the-blank quiz.
10. Simple dashboard with learned words, quiz accuracy, and weak words.

## Full Product Vision

The full version becomes a personalized AI learning companion that:

- Learns from the user's documents.
- Remembers every vocabulary interaction.
- Generates personalized flashcards.
- Builds quizzes from weak points.
- Creates conversations using recently learned words.
- Connects new topics to old knowledge.
- Tracks progress with graphs and reports.
- Builds adaptive roadmaps from placement tests.

The long-term product identity:

> An AI language learning memory system that turns everything you read and study into personalized practice.

