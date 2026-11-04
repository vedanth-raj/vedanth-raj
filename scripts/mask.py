#!/usr/bin/env python3
"""
mask.py - cut the person out of a photo so portrait.py only draws dots on you.

Needed because a dark suit on a dark studio backdrop can't be separated by
brightness alone. Uses torchvision's DeepLabV3 (COCO 'person' class); the model
weights (~230 MB) download once to the torch cache.

  python scripts/mask.py assets/photo.webp -o assets/mask.png

One-off: only rerun this when you change the photo. Requires torch + torchvision.
"""
import argparse

import numpy as np
import torch
from PIL import Image
from torchvision.models.segmentation import DeepLabV3_ResNet101_Weights, deeplabv3_resnet101

PERSON = 15  # COCO-with-VOC-labels index used by torchvision's segmentation models

p = argparse.ArgumentParser()
p.add_argument("image")
p.add_argument("-o", "--out", default="assets/mask.png")
a = p.parse_args()

w = DeepLabV3_ResNet101_Weights.DEFAULT
model = deeplabv3_resnet101(weights=w).eval()
im = Image.open(a.image).convert("RGB")
with torch.no_grad():
    prob = model(w.transforms()(im).unsqueeze(0))["out"][0].softmax(0)[PERSON]
prob = torch.nn.functional.interpolate(prob[None, None], size=im.size[::-1], mode="bilinear")[0, 0].numpy()
Image.fromarray((np.clip(prob, 0, 1) * 255).astype(np.uint8)).save(a.out)
print(f"{a.out}: person covers {(prob > 0.5).mean():.0%} of the frame")
