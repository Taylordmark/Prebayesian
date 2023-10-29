import numpy as np
import tensorflow as tf
from tensorflow import keras


from PIL import Image

from pycocotools.coco import COCO

import requests


import cv2
from utils.retina_net.retina_label_encoder import *

class CocoDSManager:
    """
    Class to manage the coco dataset and allow for smaller subsets

    annotation_pth:str path to a coco annotation json file, which can be downloaded here: https://cocodataset.org/#download
    save_pth:str directory to save images
    slice: how many images are requested
    cls_list: which classes to download images with, leave blank to get all
    """
    @tf.autograph.experimental.do_not_convert
    def __init__(self, annotation_pth:str, save_pth:str, max_samples:int=60, test_split_denominator:int = 5, cls_list:list=None, download=True, resize_size=(640, 640)) -> None:
        self.ann_pth = annotation_pth
        self.save_pth = save_pth
        self.slice = max_samples
        self.cls_list = cls_list
        self.split = test_split_denominator

        self.coco = COCO(self.ann_pth)

        # instantiate COCO specifying the annotations json path

        coco = self.coco

        # Specify a list of category names of interest
        if self.cls_list is not None:
            catIds = coco.getCatIds(catNms=self.cls_list)
            imgIds = coco.getImgIds(catIds=catIds)
        else:
            imgIds = coco.getImgIds()
        # Get the corresponding image ids and images using loadImgs

        idx = self.slice if self.slice < len(imgIds) else len(imgIds)

        imgIds = imgIds[:idx]

        img_to_load = []
        labels = coco.loadAnns(coco.getAnnIds(imgIds))

        bboxes = []
        cls_ids = []

        i = 0
        j = 0
        split_list = []

        images = []



        for label in labels:

            if (j >= len(imgIds)):
                break

            
            img = coco.loadImgs([label["image_id"]])[0]

            size = (img['width'], img['height'])
            

            if imgIds[j] == label["image_id"]:
                split_list.append(i)
                images.append(img)
                img_to_load.append(imgIds[j])
                j += 1
            i += 1

            bboxes.append(xywh_to_xyxy_percent(resize_xywh(label["bbox"], size, resize_size),resize_size))
            cls_ids.append(label["category_id"])



        #downloads images to disk 
        #TODO handle images already being there
        if download:
            images = coco.loadImgs(img_to_load)
            for im in images:
                img_data = requests.get(im['coco_url']).content
                with open(self.save_pth + "\\" + im['file_name'], 'wb') as handler:
                    handler.write(img_data)


        split_list.append(len(bboxes))

        images = self.load_images(self.save_pth, img_to_load, resize_size)

        box_tens = tf.RaggedTensor.from_row_splits(bboxes, split_list)
        cls_tens = tf.RaggedTensor.from_row_splits(cls_ids, split_list)

        full_ds = tf.data.Dataset.from_tensor_slices(
            {"image":images,
             "objects": {
             "bbox": box_tens,
             "label": cls_tens}
            })
        
        val_test_ds = full_ds.enumerate() \
                    .filter(lambda x,y: x % self.split == 0) \
                    .map(lambda x,y: y)
        
        
        self.train_ds = full_ds.enumerate() \
                    .filter(lambda x,y: x % self.split != 0) \
                    .map(lambda x,y: y)
        
        self.val_ds = val_test_ds.enumerate() \
                    .filter(lambda x,y: x % 2 == 0) \
                    .map(lambda x,y: y)
        
        
        self.test_ds = val_test_ds.enumerate() \
                    .filter(lambda x,y: x % 2 != 0) \
                    .map(lambda x,y: y)
        

    def load_images(self, path:str, ids, resize_size=(640, 640), extension=".jpg"):

        images = []

        #print(ids)

        for id in ids:
            f = path+"/"+(str(id).zfill(12))+extension
            #name, _ = f.replace(path, "").replace("\\", "").lstrip("0").split(".")

            images.append(cv2.resize(np.asarray(Image.open(f)), resize_size))
            


        return images

def resize_xywh(xywh, old_size, new_size):
    ratio = (old_size[0]/new_size[0], old_size[1]/new_size[1])

    return [xywh[0] / ratio[0], xywh[1] / ratio[1], xywh[2] / ratio[0], xywh[3]/ ratio[1]]

    #print(f"old {xywh} vs new {new_xywh}")

def xywh_to_xyxy_percent(xywh, img_size):
    return [xywh[0]/ img_size[0], xywh[1]/img_size[1], (xywh[0]+xywh[2])/img_size[0], (xywh[1]+xywh[3])/img_size[1]]

def xyxy_percent_to_yxhw(xyxy, img_size):
    return [xyxy[1]*img_size[1], xyxy[0]*img_size[0], xyxy[3]*img_size[1], xyxy[2]*img_size[0]]


def format_dataset(train_dataset, autotune, label_encoder, batch_size=4, ignore_errors=True):
    
    train_dataset = train_dataset.map(preprocess_data, num_parallel_calls=autotune)

    train_dataset = train_dataset.shuffle(8 * batch_size)
    #train_dataset = train_dataset.batch(batch_size=batch_size, drop_remainder=True)
    train_dataset = train_dataset.padded_batch(
        batch_size=batch_size, padding_values=(0.0, 1e-8, -1), drop_remainder=True
    )
    train_dataset = train_dataset.map(
        label_encoder.encode_batch, num_parallel_calls=autotune
    )
    if ignore_errors:
        train_dataset = tf.data.Dataset.ignore_errors(train_dataset)
    train_dataset = train_dataset.prefetch(autotune)

    return train_dataset


        



                    
