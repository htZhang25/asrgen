import os
from collections import defaultdict
import torch
import numpy as np
import glob
from layers import TacotronSTFT
from utils import load_wav_to_torch
from torchvision import transforms
MAX_WAV_VALUE = 32768.0
SAMPLING_RATE = 8000


def iterate_minibatches(dataset, lbl_id, lbl_id_others, batch_size,
                        shuffle=False, forever=True, length=128, to_torch=True,
                        one_hot_labels=True, apply_transform=False):

    # data augmentation for training speaker recognition
    transformer = transforms.Compose([
        lambda x: (x + 1) * 0.5,
        lambda x: x + 0.0003*torch.log(1e3*torch.rand(x.size())+1),
        transforms.ToPILImage(),
        #transforms.RandomAffine((-3, 3)),
        #transforms.RandomResizedCrop(64, (0.9, 1.0)),
        # transforms.RandomHorizontalFlip(),
        transforms.ToTensor(),
        lambda x: (x.squeeze(1) * 2) - 1])

    while True:
        data, labels = [], []
        if isinstance(lbl_id, int):
            # sample target speaker
            start_ids = np.random.choice(
                np.arange(dataset[lbl_id][0].shape[1] - length),
                batch_size,
                replace=True)
            data = [dataset[lbl_id][0][:, start_id:start_id+length]
                    for start_id in start_ids]
            labels = [lbl_id] * (batch_size)

        if len(data) and apply_transform:
            data = transformer(data)
            data = (data * 2) - 1

        # sample other speakers
        other_ids = np.random.choice(
            [i for i in lbl_id_others if i != lbl_id], batch_size, replace=True)

        for i in other_ids:
            start_id = np.random.randint(dataset[i][0].shape[1] - length)
            cur_data = dataset[i][0][:, start_id:start_id+length]
            if apply_transform:
                cur_data = transformer(cur_data.unsqueeze(0))
            data.append(cur_data)
            labels.append(i)

        if one_hot_labels:
            labels = np.eye(len(dataset))[labels]
        else:
            labels = np.array(labels, dtype=np.int64)

        if to_torch:
            data = torch.autograd.Variable(torch.stack(data))
            labels = torch.autograd.Variable(torch.from_numpy(labels).long())

        if shuffle:
            rand_ids = np.random.permutation(np.arange(len(data)))
            yield data[rand_ids], labels[rand_ids]
        else:
            yield data, labels

        if not forever:
            break


def load_data(datapath, glob_file_str, scale=True, data_split=[0.8, 0.1]):
    data = defaultdict(list)
    stft = TacotronSTFT(
        filter_length=1024, hop_length=160,
        win_length=1024, sampling_rate=16000, n_mel_channels=64,
        mel_fmin=0, mel_fmax=None, representation='asrgen')

    for folderpath in sorted(glob.glob(os.path.join(datapath, '*/'))):
        label = os.path.basename(os.path.normpath(folderpath))
        filepaths = glob.glob(os.path.join(
            os.path.join(datapath, label), glob_file_str))
        for filepath in filepaths:
            audio = load_wav_to_torch(filepath, stft.sampling_rate)
            audio_norm = audio / MAX_WAV_VALUE
            audio_norm = audio_norm / torch.max(audio_norm.abs())
            audio_norm = audio_norm.unsqueeze(0)
            audio_norm = torch.autograd.Variable(audio_norm, requires_grad=False)
            mel_spec = stft.mel_spectrogram(audio_norm)[0]
            mel_spec -= mel_spec.min()
            mel_spec = mel_spec / torch.max(mel_spec)
            mel_spec = (mel_spec * 2) - 1
            train_end = int(mel_spec.size(1)*data_split[0])
            val_end = int(mel_spec.size(1)*(data_split[0]+data_split[1]))
            data['train'].append([mel_spec[:, :train_end], label])
            data['valid'].append([mel_spec[:, train_end:val_end], label])
            data['test'].append([mel_spec[:, val_end:], label])
    return data
