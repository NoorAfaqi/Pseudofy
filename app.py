# -*- coding: utf-8 -*-
"""F219273-F219151_A3_Q2.ipynb

Automatically generated by Colab.

Original file is located at
    https://colab.research.google.com/drive/18DYHQ-7maDZJIdgRFN2yLqXw713PdPdb
"""

import math
import random
import time
import torch
import torch.nn as nn
import torch.optim as optim
import torch.nn.functional as F
import pandas as pd
from collections import Counter
from torch.nn.utils.rnn import pad_sequence
from torch.utils.data import DataLoader, Dataset
from tqdm import tqdm

PAD_TOKEN = "<pad>"
SOS_TOKEN = "<sos>"
EOS_TOKEN = "<eos>"
def simple_tokenizer(text):
    return text.strip().split()

def build_vocab(sentences, min_freq=1):
    counts = Counter(token for sentence in sentences for token in sentence)
    vocab = {PAD_TOKEN: 0, SOS_TOKEN: 1, EOS_TOKEN: 2}
    idx = len(vocab)
    for token, count in counts.items():
        if count >= min_freq and token not in vocab:
            vocab[token] = idx
            idx += 1
    return vocab
def numericalize(sentence, vocab):
    return [vocab[SOS_TOKEN]] + [vocab[token] for token in sentence if token in vocab] + [vocab[EOS_TOKEN]]

class PseudoCodeDataset(Dataset):
    def __init__(self, data, src_vocab=None, tgt_vocab=None, build_vocabs=False, reverse_columns=False):
        if isinstance(data, str):
            self.df = pd.read_csv(data)
        else:
            self.df = data.copy()
        # Force switch the first two columns if needed
        if reverse_columns:
            self.df = self.df.iloc[:, [1, 0]]
        else:
            self.df = self.df.iloc[:, :2]
        # Rename columns: first column becomes "text" (source) and second becomes "code" (target)
        self.df.columns = ["text", "code"]
        # Fill missing values in both columns
        self.df["text"] = self.df["text"].fillna("")
        self.df["code"] = self.df["code"].fillna("")
        # Tokenize the source and target strings
        self.df["src_tokens"] = self.df["text"].apply(simple_tokenizer)
        self.df["tgt_tokens"] = self.df["code"].apply(simple_tokenizer)

        if build_vocabs:
            self.src_vocab = build_vocab(self.df["src_tokens"].tolist())
            self.tgt_vocab = build_vocab(self.df["tgt_tokens"].tolist())
        else:
            self.src_vocab = src_vocab
            self.tgt_vocab = tgt_vocab

        self.df["src_indices"] = self.df["src_tokens"].apply(lambda tokens: numericalize(tokens, self.src_vocab))
        self.df["tgt_indices"] = self.df["tgt_tokens"].apply(lambda tokens: numericalize(tokens, self.tgt_vocab))
        self.data = list(zip(self.df["src_indices"].tolist(), self.df["tgt_indices"].tolist()))

    def __len__(self):
        return len(self.data)

    def __getitem__(self, idx):
        return self.data[idx]

def collate_fn(batch):
    src_batch, tgt_batch = zip(*batch)
    src_tensors = [torch.tensor(seq, dtype=torch.long) for seq in src_batch]
    tgt_tensors = [torch.tensor(seq, dtype=torch.long) for seq in tgt_batch]
    src_padded = pad_sequence(src_tensors, batch_first=True, padding_value=0)
    tgt_padded = pad_sequence(tgt_tensors, batch_first=True, padding_value=0)
    return src_padded, tgt_padded

class PositionalEncoding(nn.Module):
    def __init__(self, d_model, dropout=0.1, max_len=5000):
        super().__init__()
        self.dropout = nn.Dropout(p=dropout)
        pe = torch.zeros(max_len, d_model)
        position = torch.arange(0, max_len, dtype=torch.float).unsqueeze(1)
        div_term = torch.exp(torch.arange(0, d_model, 2).float() * (-math.log(10000.0)/d_model))
        pe[:, 0::2] = torch.sin(position * div_term)
        pe[:, 1::2] = torch.cos(position * div_term)
        self.register_buffer('pe', pe.unsqueeze(0)) # (1, max_len, d_model)
    def forward(self, x):
        return self.dropout(x + self.pe[:, :x.size(1)])

class Transformer(nn.Module):
    def __init__(self, src_vocab_size, tgt_vocab_size, d_model=512, nhead=8,
                 num_encoder_layers=6, num_decoder_layers=6, dim_feedforward=2048,
                 dropout=0.1):
        super().__init__()
        self.d_model = d_model
        self.src_embedding = nn.Embedding(src_vocab_size, d_model)
        self.tgt_embedding = nn.Embedding(tgt_vocab_size, d_model)
        self.pos_encoder = PositionalEncoding(d_model, dropout)
        self.pos_decoder = PositionalEncoding(d_model, dropout)
        self.transformer = nn.Transformer(d_model, nhead, num_encoder_layers, num_decoder_layers,
                                          dim_feedforward, dropout)
        self.fc_out = nn.Linear(d_model, tgt_vocab_size)
    def generate_square_subsequent_mask(self, sz):
        mask = (torch.triu(torch.ones(sz, sz)) == 1).transpose(0, 1)
        mask = mask.float().masked_fill(mask==0, float('-inf')).masked_fill(mask==1, float(0.0))
        return mask
    def forward(self, src, tgt):
        src_seq_len = src.size(1)
        tgt_seq_len = tgt.size(1)
        src_emb = self.src_embedding(src) * math.sqrt(self.d_model)
        src_emb = self.pos_encoder(src_emb)
        tgt_emb = self.tgt_embedding(tgt) * math.sqrt(self.d_model)
        tgt_emb = self.pos_decoder(tgt_emb)
        src_emb = src_emb.transpose(0, 1)
        tgt_emb = tgt_emb.transpose(0, 1)
        tgt_mask = self.generate_square_subsequent_mask(tgt_emb.size(0)).to(src.device)
        output = self.transformer(src_emb, tgt_emb, tgt_mask=tgt_mask)
        output = self.fc_out(output)
        return output.transpose(0, 1)

dft = pd.read_csv("spoc-train-train.tsv", sep="\t")
dfe = pd.read_csv("spoc-train-eval.tsv", sep="\t")
dfts = pd.read_csv("spoc-train-test.tsv", sep="\t")
# Sample 20% of each dataset
first_two_columns_train = dft.iloc[:, :2]
first_two_columns_eval = dfe.iloc[:, :2]
first_two_columns_test = dfts.iloc[:, :2]
print("Train Data (first two columns):")
print(first_two_columns_train.head())

train_dataset = PseudoCodeDataset(first_two_columns_train, build_vocabs=True, reverse_columns=True)
eval_dataset = PseudoCodeDataset(first_two_columns_eval, src_vocab=train_dataset.src_vocab,
                                 tgt_vocab=train_dataset.tgt_vocab, build_vocabs=False, reverse_columns=True)
test_dataset = PseudoCodeDataset(first_two_columns_test, src_vocab=train_dataset.src_vocab,
                                 tgt_vocab=train_dataset.tgt_vocab, build_vocabs=False, reverse_columns=True)
BATCH_SIZE = 64
train_loader = DataLoader(train_dataset, batch_size=BATCH_SIZE, shuffle=True, collate_fn=collate_fn)
eval_loader = DataLoader(eval_dataset, batch_size=BATCH_SIZE, shuffle=False, collate_fn=collate_fn)

# ----- Training Functions -----
def train_epoch(model, dataloader, criterion, optimizer, device):
    model.train()
    total_loss = 0
    progress_bar = tqdm(dataloader, desc="Training", leave=False)
    for src_batch, tgt_batch in progress_bar:
        src_batch, tgt_batch = src_batch.to(device), tgt_batch.to(device)
        optimizer.zero_grad()
        tgt_input = tgt_batch[:, :-1]
        tgt_expected = tgt_batch[:, 1:]
        output = model(src_batch, tgt_input)
        output = output.reshape(-1, output.size(-1))
        tgt_expected = tgt_expected.reshape(-1)
        loss = criterion(output, tgt_expected)
        loss.backward()
        optimizer.step()
        total_loss += loss.item()
        progress_bar.set_postfix(loss=loss.item())
    return total_loss / len(dataloader)

def evaluate(model, dataloader, criterion, device):
    model.eval()
    total_loss = 0
    with torch.no_grad():
        progress_bar = tqdm(dataloader, desc="Evaluating", leave=False)
        for src_batch, tgt_batch in progress_bar:
            src_batch, tgt_batch = src_batch.to(device), tgt_batch.to(device)
            tgt_input = tgt_batch[:, :-1]
            tgt_expected = tgt_batch[:, 1:]
            output = model(src_batch, tgt_input)
            output = output.reshape(-1, output.size(-1))
            tgt_expected = tgt_expected.reshape(-1)
            loss = criterion(output, tgt_expected)
            total_loss += loss.item()
            progress_bar.set_postfix(loss=loss.item())
    return total_loss / len(dataloader)

def generate_output(model, src_sentence, src_vocab, tgt_vocab, device, max_len=50):
    model.eval()
    tokens = simple_tokenizer(src_sentence)
    src_indices = numericalize(tokens, src_vocab)
    src_tensor = torch.tensor(src_indices, dtype=torch.long).unsqueeze(0).to(device)
    tgt_indices = [tgt_vocab[SOS_TOKEN]]
    for _ in range(max_len):
        tgt_tensor = torch.tensor(tgt_indices, dtype=torch.long).unsqueeze(0).to(device)
        with torch.no_grad():
            output = model(src_tensor, tgt_tensor)
        next_token = torch.argmax(output[0, -1, :]).item()
        tgt_indices.append(next_token)
        if next_token == tgt_vocab[EOS_TOKEN]:
            break
    inv_tgt_vocab = {v: k for k, v in tgt_vocab.items()}
    generated_tokens = [inv_tgt_vocab[idx] for idx in tgt_indices if idx not in (tgt_vocab[SOS_TOKEN], tgt_vocab[EOS_TOKEN])]
    return " ".join(generated_tokens)

# ----- Training Loop -----
DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")
model = Transformer(src_vocab_size=len(train_dataset.src_vocab),
                               tgt_vocab_size=len(train_dataset.tgt_vocab)).to(DEVICE)
criterion = nn.CrossEntropyLoss(ignore_index=train_dataset.src_vocab[PAD_TOKEN])
optimizer = optim.Adam(model.parameters(), lr=1e-4)
NUM_EPOCHS = 2  # Increase for a better-trained model


# Define device
device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

# Instantiate the model (assuming train_dataset is already defined)
model = Transformer(
    src_vocab_size=len(train_dataset.src_vocab),
    tgt_vocab_size=len(train_dataset.tgt_vocab)
).to(device)

# Load model checkpoint and set to evaluation mode
model.load_state_dict(torch.load("transformer_code.pth", map_location=device))
model.eval()

def generate_output(model, src_sentence, src_vocab, tgt_vocab, device, max_len=50):
    model.eval()
    tokens = simple_tokenizer(src_sentence)
    src_indices = numericalize(tokens, src_vocab)
    src_tensor = torch.tensor(src_indices, dtype=torch.long).unsqueeze(0).to(device)
    tgt_indices = [tgt_vocab[SOS_TOKEN]]

    for _ in range(max_len):
        tgt_tensor = torch.tensor(tgt_indices, dtype=torch.long).unsqueeze(0).to(device)
        with torch.no_grad():
            output = model(src_tensor, tgt_tensor)
        next_token = torch.argmax(output[0, -1, :]).item()
        tgt_indices.append(next_token)
        if next_token == tgt_vocab[EOS_TOKEN]:
            break

    inv_tgt_vocab = {v: k for k, v in tgt_vocab.items()}
    generated_tokens = [
        inv_tgt_vocab[idx] for idx in tgt_indices
        if idx not in (tgt_vocab[SOS_TOKEN], tgt_vocab[EOS_TOKEN])
    ]
    return " ".join(generated_tokens)

# ----- Inference Example -----
sample_code = "cin >> s;"
generated_pseudo = generate_output(model, sample_code, train_dataset.src_vocab, train_dataset.tgt_vocab, device)
print("\nSample C++ Code:")
print(sample_code)
print("\nGenerated Pseudocode:")
print(generated_pseudo)

import gradio as gr
import torch

# Load model
device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

# Instantiate the model (assuming train_dataset is already defined)
model = Transformer(
    src_vocab_size=len(train_dataset.src_vocab),
    tgt_vocab_size=len(train_dataset.tgt_vocab)
).to(device)

# Load model checkpoint and set to evaluation mode
model.load_state_dict(torch.load("transformer_code.pth", map_location=device))
model.eval()

# Define inference function
def generate_pseudocode(code):
    generated_pseudo = generate_output(model, code, train_dataset.src_vocab, train_dataset.tgt_vocab, device)
    return generated_pseudo

# Gradio UI
demo = gr.Interface(
    fn=generate_pseudocode,
    inputs=gr.Textbox(lines=5, placeholder="Enter C++ code here..."),
    outputs=gr.Textbox(label="Generated Pseudocode"),
    title="Code to Pseudocode Generator",
    description="Enter C++ code, and the model will generate pseudocode."
)

demo.launch()

