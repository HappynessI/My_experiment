# Copyright 2024 Bytedance Ltd. and/or its affiliates
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""
Preprocess the WebShop AgentGym trajectory dataset to parquet format for multiturn SFT.

This script converts WebShop agent-environment interaction trajectories into 
the verl multiturn format, preserving the original loss control information.
"""

import argparse
import json
import os
from typing import Dict, List, Any

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq


def convert_webshop_to_verl_multiturn(raw_traj: Dict[str, Any]) -> Dict[str, List[Dict[str, Any]]]:
    """
    Convert WebShop trajectory to verl multiturn format.
    
    The conversion follows these rules:
    - conversations[0] (human instruction) -> role: system
    - from: human (observations) -> role: user
    - from: gpt (actions) -> role: assistant
    - Preserve loss control: if loss=False, add loss_mask=0 to prevent training
    
    Args:
        raw_traj: Raw trajectory data from AgentGym WebShop format
        
    Returns:
        Dictionary with 'messages' key containing the converted conversation
    """
    raw_convs = raw_traj.get("conversations", [])
    if not raw_convs:
        return None
    
    new_messages = []
    
    # First conversation turn is the system instruction
    if raw_convs[0]['from'] == 'human':
        new_messages.append({
            "role": "system",
            "content": raw_convs[0]['value']
        })
        remaining_convs = raw_convs[1:]
    else:
        # Fallback: add default system prompt
        new_messages.append({
            "role": "system",
            "content": "You are a helpful web shopping agent."
        })
        remaining_convs = raw_convs
    
    # Process remaining conversations
    for turn in remaining_convs:
        role = "user" if turn['from'] == "human" else "assistant"
        
        # Skip assistant messages with loss=False (e.g., "Ok.")
        # These are acknowledgment messages that we don't want the model to learn
        if role == "assistant" and turn.get('loss') is False:
            continue
            
        message = {
            "role": role,
            "content": turn['value']
        }
        
        new_messages.append(message)
    
    return {"messages": new_messages}


def main():
    parser = argparse.ArgumentParser(
        description="Convert WebShop AgentGym trajectories to verl multiturn format"
    )
    parser.add_argument(
        "--input_file",
        type=str,
        required=True,
        help="Path to the input WebShop trajectory JSON file"
    )
    parser.add_argument(
        "--output_dir",
        type=str,
        default="~/data/webshop",
        help="Directory to save the output parquet files"
    )
    parser.add_argument(
        "--split_name",
        type=str,
        default="train",
        help="Name of the split (train/test/val), used for output filename"
    )
    
    args = parser.parse_args()
    
    # Expand paths
    input_file = os.path.expanduser(args.input_file)
    output_dir = os.path.expanduser(args.output_dir)
    
    # Create output directory
    os.makedirs(output_dir, exist_ok=True)
    
    print(f"Loading data from {input_file}...")
    with open(input_file, 'r', encoding='utf-8') as f:
        raw_data = json.load(f)
    
    print(f"Converting {len(raw_data)} trajectories...")
    converted_data = []
    skipped_count = 0
    
    for i, item in enumerate(raw_data):
        processed = convert_webshop_to_verl_multiturn(item)
        if processed:
            converted_data.append(processed)
        else:
            skipped_count += 1
        
        # Progress indicator
        if (i + 1) % 500 == 0:
            print(f"  Processed {i + 1}/{len(raw_data)} trajectories...")
    
    if skipped_count > 0:
        print(f"Warning: Skipped {skipped_count} invalid trajectories")
    
    # Display sample for verification BEFORE saving
    print("\n" + "="*70)
    print("Sample conversion (first 3 messages of first trajectory):")
    print("="*70)
    sample_messages = converted_data[0]["messages"][:3]
    for i, msg in enumerate(sample_messages):
        print(f"\n[Message {i}]")
        print(f"  Role: {msg['role']}")
        if 'loss_mask' in msg:
            print(f"  Loss Mask: {msg['loss_mask']} (type: {type(msg['loss_mask']).__name__})")
        content_preview = msg['content'][:200] + "..." if len(msg['content']) > 200 else msg['content']
        print(f"  Content: {content_preview}")
    print("="*70)
    
    # Save to parquet using PyArrow
    # Let PyArrow infer schema automatically - this way, messages without loss_mask
    # won't have the field at all (rather than having it with None value),
    # which prevents Pandas from converting int to float when reading
    table = pa.Table.from_pylist(converted_data)
    
    # Save using PyArrow
    output_path = os.path.join(output_dir, f"{args.split_name}.parquet")
    pq.write_table(table, output_path)
    
    # Verify the saved file has correct types
    df_loaded = pd.read_parquet(output_path)
    sample_loaded = df_loaded.iloc[0]["messages"][1]  # Check the "Ok." message
    if 'loss_mask' in sample_loaded:
        loaded_type = type(sample_loaded['loss_mask'])
        print(f"\n✓ Verification: loss_mask type is {loaded_type.__name__}")
        if loaded_type != int:
            print(f"⚠️  WARNING: loss_mask is still {loaded_type.__name__}, expected int")
    
    print(f"\n✓ Successfully converted {len(converted_data)} trajectories")
    print(f"✓ Saved to: {output_path}")
    
    # Statistics
    total_messages = sum(len(traj['messages']) for traj in converted_data)
    avg_turns = total_messages / len(converted_data) if len(converted_data) > 0 else 0
    print(f"\nStatistics:")
    print(f"  Total trajectories: {len(converted_data)}")
    print(f"  Total messages: {total_messages}")
    print(f"  Average turns per trajectory: {avg_turns:.1f}")


if __name__ == "__main__":
    main()

