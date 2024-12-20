import torch
import torch.nn as nn
from torch.nn import functional as F

class Head(nn.Module):
    """
    One head of self-attention.

    This class implements the computations for a single attention head in the self-attention mechanism.
    It projects the input into key, query, and value vectors, computes scaled dot-product attention,
    applies a causal mask to ensure autoregressive behavior, and outputs a weighted sum of values.

    Key Steps:
    1. **Projection**: Projects input into key, query, and value vectors.
    2. **Scaled Dot-Product Attention**: Computes attention weights as the scaled dot product of queries and keys.
    3. **Causal Masking**: Applies a lower triangular mask to prevent attending to future tokens, ensuring autoregressive behavior.
    4. **Weighted Sum**: Multiplies attention weights with values to produce the final output.
    5. **Dropout**: Regularizes attention weights to improve generalization.

    Args:
        config: Configuration object containing model hyperparameters.
        head_size: Dimensionality of the projected key/query/value vectors.
    """
    def __init__(self, config, head_size):
        super().__init__()
        self.key = nn.Linear(config.n_embd, head_size, bias=False)
        self.query = nn.Linear(config.n_embd, head_size, bias=False)
        self.value = nn.Linear(config.n_embd, head_size, bias=False)
        self.register_buffer('tril', torch.tril(torch.ones(config.block_size, config.block_size)))
        self.dropout = nn.Dropout(config.dropout)

    def forward(self, x):
        """
        Forward pass for the head. Computes the attention weights and applies them to the values.

        Args:
            x: Input tensor of shape (B, T, C)
        """
        B,T,C = x.shape
        k = self.key(x)
        q = self.query(x)
        wei = q @ k.transpose(-2,-1) * k.shape[-1]**-0.5
        wei = wei.masked_fill(self.tril[:T, :T] == 0, float('-inf'))
        wei = F.softmax(wei, dim=-1)
        wei = self.dropout(wei)
        v = self.value(x)
        out = wei @ v
        return out

class MultiHeadAttention(nn.Module):
    """
    Multi-head attention layer with dropout and residual connection.

    Args:
        config: Configuration object
        num_heads: Number of attention heads
        head_size: Size of each attention head
    """
    def __init__(self, config, num_heads, head_size):
        super().__init__()
        self.heads = nn.ModuleList([Head(config, head_size) for _ in range(num_heads)])
        self.proj = nn.Linear(head_size * num_heads, config.n_embd)
        self.dropout = nn.Dropout(config.dropout)

    def forward(self, x):
        out = torch.cat([h(x) for h in self.heads], dim=-1)
        out = self.dropout(self.proj(out))
        return out

class FeedForward(nn.Module):
    """
    Feed-forward layer with dropout and residual connection.

    Args:
        config: Configuration object
    """
    def __init__(self, config):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(config.n_embd, 4 * config.n_embd),
            nn.ReLU(),
            nn.Linear(4 * config.n_embd, config.n_embd),
            nn.Dropout(config.dropout),
        )

    def forward(self, x):
        return self.net(x)

class Block(nn.Module):
    """
    Block of transformer layers with self-attention and feed-forward layers.

    Args:
        config: Configuration object
    """
    def __init__(self, config):
        super().__init__()
        head_size = config.n_embd // config.n_head
        self.sa = MultiHeadAttention(config, config.n_head, head_size)
        self.ffwd = FeedForward(config)
        self.ln1 = nn.LayerNorm(config.n_embd)
        self.ln2 = nn.LayerNorm(config.n_embd)

    def forward(self, x):
        x = x + self.sa(self.ln1(x))
        x = x + self.ffwd(self.ln2(x))
        return x

class GPTLanguageModel(nn.Module):
    """
    GPT language model with transformer blocks. Generates text autoregressively.
    """
    def __init__(self, config, vocab_size):
        super().__init__()
        self.config = config

        self.token_embedding_table = nn.Embedding(vocab_size, config.n_embd)
        self.position_embedding_table = nn.Embedding(config.block_size, config.n_embd)
        self.blocks = nn.Sequential(*[Block(config) for _ in range(config.n_layer)])
        self.ln_f = nn.LayerNorm(config.n_embd)
        self.lm_head = nn.Linear(config.n_embd, vocab_size)

        self.apply(self._init_weights)

    def _init_weights(self, module):
        if isinstance(module, nn.Linear):
            torch.nn.init.normal_(module.weight, mean=0.0, std=0.02)
            if module.bias is not None:
                torch.nn.init.zeros_(module.bias)
        elif isinstance(module, nn.Embedding):
            torch.nn.init.normal_(module.weight, mean=0.0, std=0.02)

    def forward(self, idx, targets=None):
        """
        forward pass for the model

        Args:
            idx: Input tensor of token indices
            targets: Target tensor of token indices
        """
        B, T = idx.shape
        tok_emb = self.token_embedding_table(idx)
        pos_emb = self.position_embedding_table(torch.arange(T, device=self.config.device))
        x = tok_emb + pos_emb
        x = self.blocks(x)
        x = self.ln_f(x)
        logits = self.lm_head(x)

        if targets is None:
            loss = None
        else:
            B, T, C = logits.shape
            logits = logits.view(B*T, C)
            targets = targets.view(B*T)
            loss = F.cross_entropy(logits, targets)

        return logits, loss

    def generate(self, idx, max_new_tokens):
        """
        generate new tokens autoregressively given a prompt

        Args:
            idx: Input tensor of token indices
            max_new_tokens: Maximum number of new tokens to generate
        """
        for _ in range(max_new_tokens):
            idx_cond = idx[:, -self.config.block_size:]
            logits, _ = self(idx_cond)
            logits = logits[:, -1, :]
            probs = F.softmax(logits, dim=-1)
            idx_next = torch.multinomial(probs, num_samples=1)
            idx = torch.cat((idx, idx_next), dim=1)
        return idx
