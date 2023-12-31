import torch.nn as nn
import torch
from models.set_decoder import SetDecoder
from models.set_criterion import SetCriterion
from models.set_criterion_absa import SetCriterion_absa
from models.seq_encoder import SeqEncoder
from utils.functions import generate_triple
import copy
import torch.nn.functional as F
from transformers import AutoTokenizer
import os
import json
from pdb import set_trace as stop


class SetPred4RE(nn.Module):

    def __init__(self, args, num_classes):
        super(SetPred4RE, self).__init__()
        self.args = args
        self.encoder = SeqEncoder(args)
        config = self.encoder.config
        self.linear = nn.Linear(config.hidden_size, self.args.max_text_length, bias=False) # add 对应论文的公式（8），线性层没有偏置
        self.num_classes = num_classes
        self.decoder = SetDecoder(args, config, args.num_generated_triples, args.num_decoder_layers, num_classes, return_intermediate=False)
        # self.criterion = SetCriterion(num_classes, na_coef=args.na_rel_coef, losses=["entity", "relation", "quintuple_relation"], matcher=args.matcher) 
        self.criterion = SetCriterion(num_classes, na_coef=args.na_rel_coef, losses=["entity", "relation"], matcher=args.matcher) # quintuple_relation
        self.criterion_absa = SetCriterion_absa(num_classes, na_coef=args.na_rel_coef, losses=["entity", "relation"], matcher=args.matcher)
        # '--matcher', type=str, default="avg", choices=['avg', 'min']
        self.kl_loss = nn.KLDivLoss()

    def forward(self, input_ids, attention_mask, targets=None):
        last_hidden_state, pooler_output = self.encoder(input_ids, attention_mask) # hidden state, cls
        # _, pooler_output2 = self.encoder(input_ids, attention_mask)  R-drop
        
        hidden_states, class_logits, sub_start_logits, sub_end_logits, obj_start_logits, obj_end_logits, \
            aspect_start_logits, aspect_end_logits, opinion_start_logits, opinion_end_logits = self.decoder(encoder_hidden_states=last_hidden_state, encoder_attention_mask=attention_mask)
        # head_start_logits, head_end_logits, tail_start_logits, tail_end_logits = span_logits.split(1, dim=-1)
        sub_start_logits = sub_start_logits.squeeze(-1).masked_fill((1 - attention_mask.unsqueeze(1)).bool(), -10000.0)
        sub_end_logits = sub_end_logits.squeeze(-1).masked_fill((1 - attention_mask.unsqueeze(1)).bool(), -10000.0)
        obj_start_logits = obj_start_logits.squeeze(-1).masked_fill((1 - attention_mask.unsqueeze(1)).bool(), -10000.0)
        obj_end_logits = obj_end_logits.squeeze(-1).masked_fill((1 - attention_mask.unsqueeze(1)).bool(), -10000.0)
        aspect_start_logits = aspect_start_logits.squeeze(-1).masked_fill((1 - attention_mask.unsqueeze(1)).bool(), -10000.0)
        aspect_end_logits = aspect_end_logits.squeeze(-1).masked_fill((1 - attention_mask.unsqueeze(1)).bool(), -10000.0)
        opinion_start_logits = opinion_start_logits.squeeze(-1).masked_fill((1 - attention_mask.unsqueeze(1)).bool(), -10000.0)
        opinion_end_logits = opinion_end_logits.squeeze(-1).masked_fill((1 - attention_mask.unsqueeze(1)).bool(), -10000.0)
        
        outputs = { 
            'pred_rel_logits': class_logits, # bsz, q_num, num_class: (4,60,5)
            'sub_start_logits': sub_start_logits,  # bsz, q_num, seq_len: (4,60,512)
            'sub_end_logits': sub_end_logits,
            'obj_start_logits': obj_start_logits, 
            'obj_end_logits': obj_end_logits,
            'aspect_start_logits': aspect_start_logits, 
            'aspect_end_logits': aspect_end_logits,
            'opinion_start_logits': opinion_start_logits, 
            'opinion_end_logits': opinion_end_logits,
            'v_logits': hidden_states, # 直接将中间结果作为V_logits
        }


        if targets is not None:
            loss = self.criterion(outputs, targets) 
            # targets是一个list, len(targets)=bsz, targets[i]是dict，
            # dict 顺序是sub_s,sub_e, obj_s,obj_e,asp_s, asp_e, op_s,op_e, r,于outputs的顺序并不相同

            # 注意此处一个是log_softmax, 一个是softmax
            # kl_loss1 = self.kl_loss(F.log_softmax(pooler_output, dim=-1), F.softmax(pooler_output2, dim=-1)).sum(-1) # add KL loss有方向性
            # kl_loss2 = self.kl_loss(F.log_softmax(pooler_output2, dim=-1), F.softmax(pooler_output, dim=-1)).sum(-1) # add
            # kl_loss = (kl_loss1 + kl_loss2) / 2 # add 
            # loss = loss + 3 * kl_loss # add
            
            return loss, outputs
        else:
            return outputs

    def gen_triples(self, input_ids, attention_mask, info):
        with torch.no_grad():
            outputs = self.forward(input_ids, attention_mask)
            # print(outputs)
            pred_triple = generate_triple(outputs, info, self.args, self.num_classes)
            # print(pred_triple)
        return pred_triple

    @staticmethod
    def get_loss_weight(args):
        return {"relation": args.rel_loss_weight, "head_entity": args.head_ent_loss_weight, "tail_entity": args.tail_ent_loss_weight}





