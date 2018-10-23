from __future__ import print_function
import os,time,cv2, sys, math
import tensorflow as tf
import tensorflow.contrib.slim as slim
import numpy as np
import time, datetime
import argparse
import random
import os, sys
import subprocess
import glob
from imageio import imwrite

# use 'Agg' on matplotlib so that plots could be generated even without Xserver
# running
import matplotlib
matplotlib.use('Agg')

from utils import utils, helpers
from builders import model_builder

import matplotlib.pyplot as plt

# helper function for reading from iterator
def __parse_function(item):
     
    features = {"train/image": tf.FixedLenFeature([], tf.string, default_value=""),
              "train/label": tf.FixedLenFeature([], tf.string, default_value="")}
    parsed_features = tf.parse_single_example(item, features)
    img = tf.decode_raw(parsed_features['train/image'], tf.float32)
    img = tf.reshape(img,(480,640,4))
    label = tf.decode_raw(parsed_features["train/label"], tf.uint8)
    label = tf.reshape(label, (480,640))
    return img, label



def str2bool(v):
    if v.lower() in ('yes', 'true', 't', 'y', '1'):
        return True
    elif v.lower() in ('no', 'false', 'f', 'n', '0'):
        return False
    else:
        raise argparse.ArgumentTypeError('Boolean value expected.')

parser = argparse.ArgumentParser()
parser.add_argument('--num_epochs', type=int, default=300, help='Number of epochs to train for')
parser.add_argument('--epoch_start_i', type=int, default=0, help='Start counting epochs from this number')
parser.add_argument('--checkpoint_step', type=int, default=5, help='How often to save checkpoints (epochs)')
parser.add_argument('--validation_step', type=int, default=1, help='How often to perform validation (epochs)')
parser.add_argument('--image', type=str, default=None, help='The image you want to predict on. Only valid in "predict" mode.')
parser.add_argument('--continue_training', type=str2bool, default=False, help='Whether to continue training from a checkpoint')
parser.add_argument('--dataset', type=str, default="CamVid", help='Dataset you are using.')
parser.add_argument('--crop_height', type=int, default=320, help='Height of cropped input image to network')
parser.add_argument('--crop_width', type=int, default=320, help='Width of cropped input image to network')
parser.add_argument('--batch_size', type=int, default=1, help='Number of images in each batch')
parser.add_argument('--num_val_images', type=int, default=20, help='The number of images to used for validations')
parser.add_argument('--h_flip', type=str2bool, default=False, help='Whether to randomly flip the image horizontally for data augmentation')
parser.add_argument('--v_flip', type=str2bool, default=False, help='Whether to randomly flip the image vertically for data augmentation')
parser.add_argument('--brightness', type=float, default=None, help='Whether to randomly change the image brightness for data augmentation. Specifies the max bightness change as a factor between 0.0 and 1.0. For example, 0.1 represents a max brightness change of 10%% (+-).')
parser.add_argument('--rotation', type=float, default=None, help='Whether to randomly rotate the image for data augmentation. Specifies the max rotation angle in degrees.')
parser.add_argument('--model', type=str, default="FC-DenseNet56", help='The model you are using. See model_builder.py for supported models')
parser.add_argument('--frontend', type=str, default="ResNet50", help='The frontend you are using. See frontend_builder.py for supported models')
args = parser.parse_args()


def data_augmentation(input_image, output_image):
    # Data augmentation
    input_image, output_image = utils.random_crop(input_image, output_image, args.crop_height, args.crop_width)

    if args.h_flip and random.randint(0,1):
        input_image = cv2.flip(input_image, 1)
        output_image = cv2.flip(output_image, 1)
    if args.v_flip and random.randint(0,1):
        input_image = cv2.flip(input_image, 0)
        output_image = cv2.flip(output_image, 0)
    if args.brightness:
        factor = 1.0 + random.uniform(-1.0*args.brightness, args.brightness)
        table = np.array([((i / 255.0) * factor) * 255 for i in np.arange(0, 256)]).astype(np.uint8)
        input_image = cv2.LUT(input_image, table)
    if args.rotation:
        angle = random.uniform(-1*args.rotation, args.rotation)
    if args.rotation:
        M = cv2.getRotationMatrix2D((input_image.shape[1]//2, input_image.shape[0]//2), angle, 1.0)
        input_image = cv2.warpAffine(input_image, M, (input_image.shape[1], input_image.shape[0]), flags=cv2.INTER_NEAREST)
        output_image = cv2.warpAffine(output_image, M, (output_image.shape[1], output_image.shape[0]), flags=cv2.INTER_NEAREST)

    return input_image, output_image


# Get the names of the classes so we can record the evaluation results
class_names_list, label_values = helpers.get_label_info(os.path.join(args.dataset, "class_dict.csv"))
class_names_string = ""
for class_name in class_names_list:
    if not class_name == class_names_list[-1]:
        class_names_string = class_names_string + class_name + ", "
    else:
        class_names_string = class_names_string + class_name

num_classes = len(label_values)

config = tf.ConfigProto()
config.gpu_options.allow_growth = True
sess=tf.Session(config=config)

# Load the data
print("Loading the data ...")
batch_size = 5
filenames = tf.placeholder(tf.string, shape=[None])
dataset = tf.data.TFRecordDataset(filenames)
dataset = dataset.map(__parse_function)  # Parse the record into tensors.
dataset = dataset.repeat()  # Repeat the input indefinitely.
dataset = dataset.batch(batch_size)
iterator = dataset.make_initializable_iterator()
next_example, next_label = iterator.get_next()
next_label = tf.one_hot(tf.cast(next_label, tf.uint8),depth=num_classes, axis=3)

print(next_label.get_shape())
#next_example, next_label = helpers.random_crop_and_pad_image_and_labels(image=next_example, labels=next_label, size=[args.crop_height, args.crop_width])

train_names = glob.glob(os.getcwd()+"/dataset/tfrecord/train/*.tfrecord")
test_names = glob.glob(os.getcwd()+"/dataset/tfrecord/test/*.tfrecord")
val_names = glob.glob(os.getcwd()+"/dataset/tfrecord/validation/*.tfrecord")

# Compute your softmax cross entropy loss
net_input = next_example
net_output = next_label

network, init_fn = model_builder.build_model(model_name=args.model, frontend=args.frontend, net_input=net_input, num_classes=num_classes, crop_width=args.crop_width, crop_height=args.crop_height, is_training=True)

loss = tf.reduce_mean(tf.nn.softmax_cross_entropy_with_logits(logits=network, labels=net_output))

iou, _ = tf.metrics.mean_iou(labels=net_output, predictions=network, num_classes=num_classes)

mean_per_class_accuracy, _ = tf.metrics.mean_per_class_accuracy(labels=net_output, predictions=network, num_classes=num_classes)

precision, _ = tf.metrics.precision(labels=net_output, predictions=network)

f1_score, _ = tf.contrib.metrics.f1_score(labels=net_output, predictions=network)

opt = tf.train.RMSPropOptimizer(learning_rate=0.0001, decay=0.995).minimize(loss, var_list=[var for var in tf.trainable_variables()])

saver=tf.train.Saver(max_to_keep=1000)
sess.run(tf.global_variables_initializer())

utils.count_params()

# If a pre-trained ResNet is required, load the weights.
# This must be done AFTER the variables are initialized with sess.run(tf.global_variables_initializer())
if init_fn is not None:
    init_fn(sess)

# Load a previous checkpoint if desired
model_checkpoint_name = "checkpoints/latest_model_" + args.model + "_" + args.dataset + ".ckpt"
if args.continue_training:
    print('Loaded latest model checkpoint')
    saver.restore(sess, model_checkpoint_name)

print("\n***** Begin training *****")
print("Dataset -->", args.dataset)
print("Model -->", args.model)
print("Crop Height -->", args.crop_height)
print("Crop Width -->", args.crop_width)
print("Num Epochs -->", args.num_epochs)
print("Batch Size -->", args.batch_size)
print("Num Classes -->", num_classes)

print("Data Augmentation:")
print("\tVertical Flip -->", args.v_flip)
print("\tHorizontal Flip -->", args.h_flip)
print("\tBrightness Alteration -->", args.brightness)
print("\tRotation -->", args.rotation)
print("")

avg_loss_per_epoch = []
avg_iou_per_epoch = []
avg_acc_per_epoch = []
avg_prec_per_epoch = []
avg_f1_score_per_epoch = []
avg_val_loss_per_epoch = []
avg_val_iou_per_epoch = []
avg_val_acc_per_epoch = []
avg_val_prec_per_epoch = []
avg_val_f1_score_per_epoch = []

# Which validation images do we want
val_indices = []

# Set random seed to make sure models are validated on the same validation images.
# So you can compare the results of different models more intuitively.
random.seed(16)

# Do the training here
for epoch in range(args.epoch_start_i, args.num_epochs):

    current_losses = []
    current_accs = []
    current_prec = []
    current_iou = []
    current_f1_score = []

    cnt=0

    num_iters = 5
    st = time.time()
    epoch_st=time.time()

    # initialize dataset iterator
    sess.run(iterator.initializer, feed_dict={filenames: train_names})

    # initialize local variables inside metrics 
    sess.run(tf.local_variables_initializer())

    for i in range(num_iters):
        # st=time.time()

        input_image_batch = []
        output_image_batch = []
        
        print("Training.....")
        # Do the training
        img, label, _, current, iou_, mean_per_class_accuracy_, precision_, f1_ = sess.run([next_example, next_label, opt, loss,iou,mean_per_class_accuracy, precision, f1_score])
        
        # debug
        if i == 0:
            img = img[0]
            imwrite("trial.png", img[:,:,:3])
            imwrite("label.png", helpers.colour_code_segmentation(helpers.reverse_one_hot(label[0]), label_values))


        print("Loss: ", current)
        print("IOU: ", iou_)
        current_losses.append(current)
        current_accs.append(mean_per_class_accuracy_)
        current_iou.append(iou_)
        current_prec.append(precision_)
        current_f1_score.append(f1_)

        cnt = cnt + args.batch_size
        if cnt % 20 == 0:
            string_print = "Epoch = %d Count = %d Current_Loss = %.4f Time = %.2f"%(epoch,cnt,current,time.time()-st)
            utils.LOG(string_print)
            st = time.time()

    mean_loss = np.mean(current_losses)
    mean_acc = np.mean(current_accs)
    mean_prec = np.mean(current_prec)
    mean_iou = np.mean(current_iou)
    mean_f1 = np.mean(current_f1_score)
    avg_loss_per_epoch.append(mean_loss)
    avg_iou_per_epoch.append(mean_iou)
    avg_acc_per_epoch.append(mean_acc)
    avg_prec_per_epoch.append(mean_prec)
    avg_f1_score_per_epoch.append(mean_f1)

    # Create directories if needed
    if not os.path.isdir("%s/%04d"%("checkpoints",epoch)):
        os.makedirs("%s/%04d"%("checkpoints",epoch))

    # Save latest checkpoint to same file name
    print("Saving latest checkpoint")
    saver.save(sess,model_checkpoint_name)

    if val_indices != 0 and epoch % args.checkpoint_step == 0:
        print("Saving checkpoint for this epoch")
        saver.save(sess,"%s/%04d/model.ckpt"%("checkpoints",epoch))


    if epoch % args.validation_step == 0:
        print("Performing validation")
        target=open("%s/%04d/val_scores.csv"%("checkpoints",epoch),'w')
        target.write("val_name, avg_accuracy, precision, recall, f1 score, mean iou, %s\n" % (class_names_string))

        current_losses = []
        current_accs = []
        current_prec = []
        current_iou = []
        current_f1_score = []

        # Do the validation on a small set of validation images
        sess.run(iterator.initializer, feed_dict={filenames: val_names})

        val_iters = 5
        for i in range(val_iters):
            _, current_loss, iou_, acc_, precision_, f1_ = sess.run([opt, loss, iou, mean_per_class_accuracy, precision, f1_score])
            current_losses.append(current_loss)
            current_iou.append(iou_)
            current_accs.append(acc_)
            current_prec.append(precision_)
            current_f1_score.append(f1_)
        
        avg_val_acc_per_epoch.append(np.mean(current_accs))
        avg_val_f1_score_per_epoch.append(np.mean(current_f1_score))
        avg_val_iou_per_epoch.append(np.mean(current_f1_score))
        avg_val_prec_per_epoch.append(np.mean(current_prec))
        avg_val_loss_per_epoch.append(np.mean(current_losses))

        # print visualization of a batch
        ims, gts, output_images = sess.run([next_example, next_label, network])

        for j in range(ims.shape[0]):
            output_image = np.array(output_images[j])
            output_image = helpers.reverse_one_hot(output_image)
            gt = helpers.reverse_one_hot(gts[j])
            out_vis_image = helpers.colour_code_segmentation(output_image, label_values)

            file_name = f"img{j}.png"

            gt = helpers.colour_code_segmentation(gt, label_values)

            cv2.imwrite("%s/%04d/%s_pred.png"%("checkpoints",epoch, file_name),cv2.cvtColor(np.uint8(out_vis_image), cv2.COLOR_RGB2BGR))
            cv2.imwrite("%s/%04d/%s_gt.png"%("checkpoints",epoch, file_name),cv2.cvtColor(np.uint8(gt), cv2.COLOR_RGB2BGR))

        target.close()

        print("\nAverage validation accuracy for epoch # %04d = %f"% (epoch, np.mean(current_accs)))
        print("Validation precision = ", np.mean(current_prec))
        print("Validation F1 score = ", np.mean(current_f1_score))
        print("Validation IoU score = ", np.mean(current_iou))

    epoch_time=time.time()-epoch_st
    remain_time=epoch_time*(args.num_epochs-1-epoch)
    m, s = divmod(remain_time, 60)
    h, m = divmod(m, 60)
    if s!=0:
        train_time="Remaining training time = %d hours %d minutes %d seconds\n"%(h,m,s)
    else:
        train_time="Remaining training time : Training completed.\n"
    utils.LOG(train_time)

    if epoch % 5 == 0:

        fig1, ax1 = plt.subplots(figsize=(11, 8))

        ax1.plot(range(epoch+1), avg_val_acc_per_epoch)
        ax1.set_title("Average validation accuracy vs epochs")
        ax1.set_xlabel("Epoch")
        ax1.set_ylabel("Avg. val. accuracy")


        plt.savefig('accuracy_vs_epochs.png')

        plt.clf()

        fig2, ax2 = plt.subplots(figsize=(11, 8))

        ax2.plot(range(epoch+1), avg_val_loss_per_epoch)
        ax2.set_title("Average loss vs epochs")
        ax2.set_xlabel("Epoch")
        ax2.set_ylabel("Current loss")

        plt.savefig('loss_vs_epochs.png')

        plt.clf()

        fig3, ax3 = plt.subplots(figsize=(11, 8))

        ax3.plot(range(epoch+1), avg_val_iou_per_epoch)
        ax3.set_title("Average val IoU vs epochs")
        ax3.set_xlabel("Epoch")
        ax3.set_ylabel("Current IoU")

        plt.savefig('iou_vs_epochs.png')

        plt.clf()

        fig4, ax4 = plt.subplots(figsize=(11, 8))

        ax4.plot(range(epoch+1), avg_acc_per_epoch)
        ax4.set_title("Average training accuracy vs epochs")
        ax4.set_xlabel("Epoch")
        ax4.set_ylabel("Accuracy")

        plt.savefig('tra_acc_vs_epochs.png')

        plt.clf()

        fig5, ax5 = plt.subplots(figsize=(11, 8))

        ax5.plot(range(epoch+1), avg_iou_per_epoch)
        ax5.set_title("Average training iou vs epochs")
        ax5.set_xlabel("Epoch")
        ax5.set_ylabel("IOU")

        plt.savefig('tra_iou_vs_epochs.png')

        plt.clf()

        fig6, ax6 = plt.subplots(figsize=(11, 8))

        ax6.plot(range(epoch+1), avg_loss_per_epoch)
        ax6.set_title("Average training loss vs epochs")
        ax6.set_xlabel("Epoch")
        ax6.set_ylabel("Current loss")

        plt.savefig('Tra_loss_vs_epochs.png')

        plt.clf()


